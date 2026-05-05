#!/bin/bash
cd "$(dirname "$0")/.."

START=${1:-1}

ALL_TESTS=(
    "tests/layer2/test_smoke.py::test_first_run_auth_prompt"
    "tests/layer2/test_smoke.py::test_first_run_set_api_key"
    "tests/layer2/test_smoke.py::test_first_run_discogs_credentials"
    "tests/layer2/test_smoke.py::test_first_run_field_mappings"
    "tests/layer2/test_smoke.py::test_collection_home_loads"
    "tests/layer2/test_smoke.py::test_collection_tile_view"
    "tests/layer2/test_smoke.py::test_column_sort"
    "tests/layer2/test_smoke.py::test_group_by_artist"
    "tests/layer2/test_smoke.py::test_format_filter_bar"
    "tests/layer2/test_smoke.py::test_search_bar_filters"
)

TESTS=("${ALL_TESTS[@]:$((START-1))}")

EXTRA_FLAGS=""
if [ "$START" -eq 1 ]; then
    EXTRA_FLAGS="--full-reset"
elif [ "$START" -ge 3 ]; then
    EXTRA_FLAGS="--inject-api-key"
fi

/home/kieran/.venvs/sleevenotes-tests/bin/python -m pytest \
    "${TESTS[@]}" \
    $EXTRA_FLAGS --headed --slowmo=1500 -v -s -m smoke
