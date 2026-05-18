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

from typing import Any, Dict, List
from urllib.parse import urlparse


ARM_CONTENT_DISCLAIMER = (
    "This information is derived from materials available on an arm.com subdomain and is subject to the "
    "terms and conditions applicable to the original source content. You should refer to the original "
    "materials for the full terms of use. Except where expressly stated in those terms or in a separate "
    "current and valid license from Arm to the information described, no license to any intellectual "
    "property rights is granted by Arm to use or implement this information."
)


def is_arm_domain_url(url: str | None) -> bool:
    if not url:
        return False

    hostname = urlparse(url).hostname
    if not hostname:
        return False

    hostname = hostname.lower().rstrip(".")
    return hostname == "arm.com" or hostname.endswith(".arm.com")


def add_disclaimer_to_arm_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {**item, "disclaimer": ARM_CONTENT_DISCLAIMER} if is_arm_domain_url(item.get("url")) else item
        for item in results
    ]
