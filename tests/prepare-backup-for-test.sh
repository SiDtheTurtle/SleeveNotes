#!/bin/bash
cd "$(dirname "$0")/.."
/home/kieran/.venvs/sleevenotes-tests/bin/python tests/prepare-backup-for-test.py "$@"
