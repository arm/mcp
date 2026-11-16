# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared filter validation for Python callers and JSON request bodies."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from arm_kb_search import SearchFilters
from arm_kb_search.filters import MetadataFilterIndex


def test_filters_round_trip_through_endpoint_request_and_keep_matching():
    class Request(BaseModel):
        filters: SearchFilters

    payload = {"filters": {"platform": [" Linux ", "WINDOWS", "linux"],
                           "product": " ARM ", "edition": None}}
    request = Request.model_validate_json(json.dumps(payload))
    filters = request.filters
    assert filters.platform == ("linux", "windows")
    assert filters.product == "arm"
    assert SearchFilters.parse(filters) is filters
    assert SearchFilters.model_validate(filters.model_dump()) == filters
    assert json.loads(request.model_dump_json(exclude_none=True)) == {
        "filters": {"platform": ["linux", "windows"], "product": "arm"}}
    assert filters.model_dump(mode="json", exclude_none=True) == {
        "platform": ["linux", "windows"], "product": "arm"}
    lookup = MetadataFilterIndex([
        {"platform": "linux", "product": "Arm"},
        {"platform": "windows", "product": "Arm"},
        {"platform": "macos", "product": "Arm"},
        {"platform": "linux", "product": "other"},
        {"product": "Arm"},
    ])
    assert lookup.eligible_ids(filters) == (0, 1)
    with pytest.raises(ValidationError, match="frozen"):
        filters.platform = "macos"
    assert lookup.eligible_ids(filters) == (0, 1)


@pytest.mark.parametrize("payload", [
    {"platform": 1}, {"platform": True}, {"platform": []},
    {"platform": ["linux", 1]}, {"platform": ["linux", " "]},
    {"platform": [["linux"]]}, {"unknown": "linux"},
])
def test_json_filters_reject_invalid_values_and_unknown_fields(payload):
    with pytest.raises(ValidationError):
        SearchFilters.model_validate_json(json.dumps(payload))
