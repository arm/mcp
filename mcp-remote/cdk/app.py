# Copyright © 2025, Arm Limited and Contributors. All rights reserved.
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

import os
from aws_cdk import DefaultStackSynthesizer, Stack, Environment, App
import mcp_stack

app = App(default_stack_synthesizer=DefaultStackSynthesizer(
		deploy_role_arn="arn:${AWS::Partition}:iam::${AWS::AccountId}:role/Proj-cdk-${Qualifier}-deploy-role-${AWS::AccountId}-${AWS::Region}",
		file_asset_publishing_role_arn="arn:${AWS::Partition}:iam::${AWS::AccountId}:role/Proj-cdk-${Qualifier}-file-publishing-role-${AWS::AccountId}-${AWS::Region}",
		image_asset_publishing_role_arn="arn:${AWS::Partition}:iam::${AWS::AccountId}:role/Proj-cdk-${Qualifier}-image-publishing-role-${AWS::AccountId}-${AWS::Region}",
		cloud_formation_execution_role="arn:${AWS::Partition}:iam::${AWS::AccountId}:role/Proj-cdk-${Qualifier}-cfn-exec-role-${AWS::AccountId}-${AWS::Region}",
		lookup_role_arn="arn:${AWS::Partition}:iam::${AWS::AccountId}:role/Proj-cdk-${Qualifier}-lookup-role-${AWS::AccountId}-${AWS::Region}"
	))

# Create an Environment object specifying the region
env = Environment(region="us-west-2", account=os.environ["AWS_ACCOUNT_NUMBER"])

# Pass the env to the stack
mcp_stack.McpSimilaritySearchStack(app, "McpSimilaritySearchStack", env=env)

app.synth()