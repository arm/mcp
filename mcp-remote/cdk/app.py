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