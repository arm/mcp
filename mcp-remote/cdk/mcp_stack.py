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

from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_autoscaling as autoscaling,
    aws_iam as iam,
    Tags,
    CfnOutput,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
)
from constructs import Construct

class McpSimilaritySearchStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a new VPC
        vpc = ec2.Vpc.from_lookup(self, "VPC",
                                  vpc_id=os.environ["VPC_ID"]
                                  )

        # Create a security group for the EC2 instances
        security_group = ec2.SecurityGroup(self, "McpSecurityGroup",
                                           vpc=vpc,
                                           allow_all_outbound=True,
                                           description="Security group for EC2 instances"
                                           )
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(5000), "Allow incoming traffic on port 5000")

        # Create a launch template
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "apt-get update",
            "apt-get install -y python3-pip nginx",
            # Install SSM agent
            "sudo snap install amazon-ssm-agent --classic",
            "sudo systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service",
            "sudo systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service",
            # Log SSM agent status for troubleshooting
            "sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service >> /var/log/ssm-setup.log",
            "echo 'SSM agent installation complete' >> /var/log/ssm-setup.log",
            # Check if instance can reach SSM endpoints
            "curl -v https://ssm.eu-west-1.amazonaws.com >> /var/log/ssm-connectivity-test.log 2>&1",
            # Instll AWS CLI
            "apt install unzip",
            'curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"',
            "unzip awscliv2.zip",
            "sudo ./aws/install",
        )

        # Look up the latest Ubuntu 24.04 ARM64 AMI
        ubuntu_arm_ami = ec2.MachineImage.lookup(
            name="ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*",
            owners=["099720109477"],  # Canonical's AWS account ID
            filters={"architecture": ["arm64"]}
        )

        permissions_boundary = iam.ManagedPolicy.from_managed_policy_arn(
            self,
            "PermissionsBoundary",
            managed_policy_arn="arn:aws:iam::688080325088:policy/ProjAdminsPermBoundaryv2"
        )

        ec2_role = iam.Role(self, "EC2Role",
                            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                            managed_policies=[
                                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"),
                                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess"),
                                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess")
                            ],
                            permissions_boundary=permissions_boundary,
                            role_name="Proj-MCP-ALB-EC2-Role",
                            )

        launch_template = ec2.LaunchTemplate(self, "LaunchTemplate",
                                             instance_type=ec2.InstanceType("m8g.large"),
                                             machine_image=ubuntu_arm_ami,
                                             user_data=user_data,
                                             security_group=security_group,
                                             role=ec2_role,
                                             detailed_monitoring=True,
                                             block_devices=[
                                                 ec2.BlockDevice(
                                                     device_name="/dev/sda1",
                                                     volume=ec2.BlockDeviceVolume.ebs(
                                                         volume_size=50,
                                                         volume_type=ec2.EbsDeviceVolumeType.GP3,
                                                         delete_on_termination=True
                                                     )
                                                 )
                                             ]
                                             )

        # Create an Auto Scaling Group
        asg = autoscaling.AutoScalingGroup(self, "ASG",
                                           vpc=vpc,
                                           vpc_subnets=ec2.SubnetSelection(
                                               subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                                           launch_template=launch_template,
                                           min_capacity=1,
                                           max_capacity=1,
                                           desired_capacity=1
                                           )

        # Create an Application Load Balancer
        alb = elbv2.ApplicationLoadBalancer(self, "ALB",
                                            vpc=vpc,
                                            internet_facing=True,
                                            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
                                            )

        # Generate a certificate for the ALB's default domain
        certificate = acm.Certificate.from_certificate_arn(
            self,
            "Certificate",
            os.environ["ACM_CERTIFICATE_ARN"]
        )

        # Add a listener to the ALB with HTTPS
        listener = alb.add_listener("HttpsListener",
                                    port=443,
                                    certificates=[certificate],
                                    ssl_policy=elbv2.SslPolicy.RECOMMENDED)

        # Add the ASG as a target to the ALB listener
        listener.add_targets("ASGTarget",
                             port=5000,
                             targets=[asg],
                             protocol=elbv2.ApplicationProtocol.HTTP,
                             health_check=elbv2.HealthCheck(
                                 path="/health",
                                 healthy_http_codes="200-299"
                             ))

        hosted_zone = route53.HostedZone.from_lookup(self, "HostedZone",
                                                     domain_name=os.environ["HOSTED_ZONE_DOMAIN_NAME"],
                                                     )

        # Create an A record for the subdomain
        route53.ARecord(self, "ALBDnsRecord",
                        zone=hosted_zone,
                        record_name=os.environ["SUBDOMAIN_NAME"],
                        target=route53.RecordTarget.from_alias(targets.LoadBalancerTarget(alb))
                        )

        # Output the ALB DNS name
        CfnOutput(self, "LoadBalancerDNS",
                  value=alb.load_balancer_dns_name,
                  description="The DNS name of the Application Load Balancer")