#!/bin/bash
cd "$(dirname "$0")/.."

ARG=${1:-"1+"}

ALL_TESTS=(
    "tests/layer2/test_smoke.py::test_first_run_auth_prompt"
    "tests/layer2/test_smoke.py::test_first_run_set_api_key"
    "tests/layer2/test_smoke.py::test_first_run_discogs_credentials"
    "tests/layer2/test_smoke.py::test_first_run_field_mappings"
    "tests/layer2/test_smoke.py::test_collection_home_loads"
    "tests/layer2/test_smoke.py::test_collection_tile_view"
    "tests/layer2/test_smoke.py::test_record_detail_tile"
    "tests/layer2/test_smoke.py::test_column_sort"
    "tests/layer2/test_smoke.py::test_group_by_artist"
    "tests/layer2/test_smoke.py::test_format_filter_bar"
    "tests/layer2/test_smoke.py::test_search_bar_filters"
    "tests/layer2/test_smoke.py::test_surprise_me"
    "tests/layer2/test_smoke.py::test_record_detail_fields"
    "tests/layer2/test_smoke.py::test_tracklist_with_headings"
    "tests/layer2/test_smoke.py::test_record_modal_navigation"
    "tests/layer2/test_smoke.py::test_cover_image_lightbox"
    "tests/layer2/test_smoke.py::test_sync_metadata"
    "tests/layer2/test_smoke.py::test_sync_custom_fields"
    "tests/layer2/test_smoke.py::test_edit_record_fields"
    "tests/layer2/test_smoke.py::test_use_as_cover"
    "tests/layer2/test_smoke.py::test_add_record"
    "tests/layer2/test_smoke.py::test_delete_record"
    "tests/layer2/test_smoke.py::test_wishlist_section_loads"
    "tests/layer2/test_smoke.py::test_wishlist_column_sort"
    "tests/layer2/test_smoke.py::test_wishlist_tile_view"
    "tests/layer2/test_smoke.py::test_wishlist_search_modal"
    "tests/layer2/test_smoke.py::test_wishlist_detail_modal"
    "tests/layer2/test_smoke.py::test_add_to_wishlist"
    "tests/layer2/test_smoke.py::test_wishlist_match_prompt"
    "tests/layer2/test_smoke.py::test_wishlist_unfulfil"
    "tests/layer2/test_smoke.py::test_wishlist_show_fulfilled_toggle"
    "tests/layer2/test_smoke.py::test_wishlist_notes_persist"
    "tests/layer2/test_smoke.py::test_mark_wishlist_fulfilled"
    "tests/layer2/test_smoke.py::test_delete_wishlist_item"
)

TOTAL=${#ALL_TESTS[@]}

if [[ "$ARG" =~ ^([0-9]+)\+$ ]]; then
    START=${BASH_REMATCH[1]}
    END=$TOTAL
elif [[ "$ARG" =~ ^([0-9]+)-([0-9]+)$ ]]; then
    START=${BASH_REMATCH[1]}
    END=${BASH_REMATCH[2]}
elif [[ "$ARG" =~ ^([0-9]+)$ ]]; then
    START=$ARG
    END=$ARG
else
    echo "Usage: $0 [N | N+ | N-M]"
    exit 1
fi

TESTS=("${ALL_TESTS[@]:$((START-1)):$((END-START+1))}")

EXTRA_FLAGS=""
if [ "$START" -eq 1 ]; then
    EXTRA_FLAGS="--full-reset"
elif [ "$START" -ge 3 ]; then
    EXTRA_FLAGS="--inject-api-key"
fi

/home/kieran/.venvs/sleevenotes-tests/bin/python -m pytest \
    "${TESTS[@]}" \
    $EXTRA_FLAGS --headed --slowmo=1500 -v -s -m smoke
