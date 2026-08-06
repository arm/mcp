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

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.kb_response import ARM_CONTENT_DISCLAIMER, add_disclaimer_to_arm_results, is_arm_domain_url


def test_is_arm_domain_url_matches_arm_domains_and_subdomains():
    assert is_arm_domain_url("https://arm.com/products")
    assert is_arm_domain_url("https://developer.arm.com/documentation")
    assert is_arm_domain_url("https://learn.arm.com/learning-paths/")
    assert is_arm_domain_url("https://deep.subdomain.arm.com/path")
    assert is_arm_domain_url("https://LEARN.ARM.COM/path")


def test_is_arm_domain_url_rejects_non_arm_domains():
    assert not is_arm_domain_url("https://example.com")
    assert not is_arm_domain_url("https://arm.com.example.com")
    assert not is_arm_domain_url("https://developer-arm.com")
    assert not is_arm_domain_url("not a url")
    assert not is_arm_domain_url(None)


def test_add_disclaimer_to_arm_results_adds_disclaimer_per_arm_url():
    arm_result = {"url": "https://learn.arm.com/learning-paths/servers-and-cloud-computing/sve2-match/"}
    non_arm_result = {"url": "https://amperecomputing.com/tuning-guides/nginx-tuning-guide"}

    assert add_disclaimer_to_arm_results([arm_result, non_arm_result]) == [
        {**arm_result, "disclaimer": ARM_CONTENT_DISCLAIMER},
        non_arm_result,
    ]


def test_add_disclaimer_to_arm_results_preserves_list_shape_without_arm_urls():
    results = [{"url": "https://amperecomputing.com/tuning-guides/nginx-tuning-guide"}]

    assert add_disclaimer_to_arm_results(results) == results
