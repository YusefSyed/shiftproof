# Third-party notices

ShiftProof depends on the packages pinned in `pyproject.toml` and `uv.lock`. Their licenses remain governed by their respective upstream projects.

| Package | License reported by installed package metadata | Project |
| --- | --- | --- |
| Strands Agents | Apache-2.0 | https://github.com/strands-agents/harness-sdk |
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Uvicorn | BSD-3-Clause | https://www.uvicorn.org/ |
| Pydantic | MIT | https://github.com/pydantic/pydantic |
| HTTPX | BSD-3-Clause | https://github.com/encode/httpx |
| OR-Tools | Apache-2.0 | https://developers.google.com/optimization/ |
| icalendar | BSD-2-Clause | https://icalendar.readthedocs.io/ |
| python-multipart | Apache-2.0 | https://github.com/Kludex/python-multipart |

See each upstream distribution for its complete license text and any transitive dependency notices.

## Demo media

The ignored local demo-render workspace uses `kokoro-onnx` 0.4.9 (MIT) with the Kokoro v1.0 ONNX model and voices release (Apache-2.0). The renderer records the exact release URL and SHA-256 values in `media-work/kokoro/receipt.json`; model files are not distributed in this repository.
