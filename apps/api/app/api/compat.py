try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.responses import FileResponse, StreamingResponse
except ModuleNotFoundError:  # pragma: no cover
    class APIRouter:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def patch(self, *args, **kwargs):
            return lambda fn: fn

    def Depends(value=None):  # type: ignore
        return value

    def Query(default=None, **kwargs):  # type: ignore
        return default

    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int, detail: str) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class FileResponse:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            pass

    class StreamingResponse:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            pass

