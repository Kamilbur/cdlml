# Running tests

## glibc (host)

Requires: `gcc`, `make`, `libffi-dev`.

```
pip install -e .[dev]
pytest
```

## musl (Docker / Alpine)

Builds Alpine image with `libffi-dev`, compiles the package with `CDLML_DEBUG=1`
(disables the `_cdlml` C extension; uses `cdlml_server` fallback path instead of dlmopen),
then runs the full suite inside the container.

```
docker buildx build -t cdlml -f tests/Dockerfile .
docker run --rm -it cdlml
```

---

## Test suites

### `test_preload/`

Verifies per-instance LD_PRELOAD symbol interposition. A `libmalloc.so` interposer
shadows `malloc` and writes `[interpose] malloc(size=N)` to stderr on every call.
`libfoo.so` uses `malloc` internally; `libbar.so` does not.

Each of the 15 parametrized cases calls `foo` and `bar` functions in various
sequences with the interposer enabled/disabled (via a `mapping_enabled` flag),
then asserts that captured stderr matches exactly the expected sequence of
`malloc` calls.

### `test_arbitrary_args/`

Verifies libffi-based argument and return-value dispatch across all supported
type codes: `void`, `i32`, `i64`, `u32`, `u64`, `f32`, `f64`, `cstr`.

Cases include boundary values (`INT32_MIN`, `INT64_MAX`, `UINT64_MAX`),
unsigned overflow wrap, float/double round-trip precision, `f64→f32` cast,
multi-arg calls (3 args), and `strlen` via a `c_char_p` argument.
Float comparisons use `pytest.approx`.

Runs against whichever `PreloadedCDLL` backend is available: dlmopen on glibc,
`cdlml_server` + libffi on musl.
