# Vietcap protobuf

The frontend schema was retrieved without credentials from:

`https://trading.vietcap.com.vn/protos/price.proto`

Retrieval evidence from 2026-09-19:

- HTTP status: `200`
- Content type: `application/octet-stream`
- Size: `6319` bytes
- Upstream SHA-256: `e548eca5699fec2af3e49dca32366d9db231b06db3d99521a70aaba27aca3b4c`

The upstream file places `package pricePackage;` before `syntax = "proto3";`.
`protobuf.js` accepts that ordering, but the standard protobuf compiler rejects it.
The vendored `price.proto` swaps only those first two declarations. A content
comparison confirms that no other byte differs after applying that normalization.

Generate the Python binding from the project root:

```powershell
.\.venv\Scripts\python.exe -m grpc_tools.protoc -I. --python_out=. data/vietcap/proto/price.proto
```

Do not hand-edit `price_pb2.py`. If the endpoint changes, re-fetch the schema,
review the diff, regenerate the binding, run the tests, and update
`PROJECT_CONTEXT.md` with new runtime evidence.
