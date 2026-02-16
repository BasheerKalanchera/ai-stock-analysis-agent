"""
Custom serializer for LangGraph PostgreSQL Checkpointer.
Handles io.BytesIO and pd.DataFrame types found in StockAnalysisState,
which are not natively supported by the default JsonPlusSerializer.
"""
import io
import base64
import pandas as pd
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


class StockAnalysisSerializer(JsonPlusSerializer):
    """Extends JsonPlusSerializer to handle io.BytesIO and pd.DataFrame.
    
    BytesIO objects are converted to base64-encoded strings for storage.
    DataFrames are converted to JSON (split orientation) for storage.
    Both are transparently reconstructed on load.
    """

    def dumps(self, obj):
        return super().dumps(self._preprocess(obj))

    def dumps_typed(self, obj):
        return super().dumps_typed(self._preprocess(obj))

    def loads(self, data):
        return self._postprocess(super().loads(data))

    def loads_typed(self, data):
        return self._postprocess(super().loads_typed(data))

    def _preprocess(self, obj):
        """Convert non-serializable types before JSON encoding."""
        if isinstance(obj, io.BytesIO):
            return {
                "__custom_type__": "BytesIO",
                "__data__": base64.b64encode(obj.getvalue()).decode()
            }
        elif isinstance(obj, bytes):
            return {
                "__custom_type__": "bytes",
                "__data__": base64.b64encode(obj).decode()
            }
        elif isinstance(obj, pd.DataFrame):
            return {
                "__custom_type__": "DataFrame",
                "__data__": obj.to_json(orient="split")
            }
        elif isinstance(obj, dict):
            return {k: self._preprocess(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._preprocess(item) for item in obj]
        return obj

    def _postprocess(self, obj):
        """Reconstruct custom types after JSON decoding."""
        if isinstance(obj, dict):
            custom_type = obj.get("__custom_type__")
            if custom_type == "BytesIO":
                return io.BytesIO(base64.b64decode(obj["__data__"]))
            elif custom_type == "bytes":
                return base64.b64decode(obj["__data__"])
            elif custom_type == "DataFrame":
                return pd.read_json(io.StringIO(obj["__data__"]), orient="split")
            return {k: self._postprocess(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._postprocess(item) for item in obj]
        return obj
