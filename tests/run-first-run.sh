#!/bin/bash
cd "$(dirname "$0")/.."
/home/kieran/.venvs/sleevenotes-tests/bin/python -m pytest tests/layer2/test_smoke.py::test_first_run_auth_prompt tests/layer2/test_smoke.py::test_first_run_set_api_key tests/layer2/test_smoke.py::test_first_run_discogs_credentials tests/layer2/test_smoke.py::test_first_run_field_mappings -m "smoke and first_run" --full-reset --headed --slowmo=1500 -v -s
