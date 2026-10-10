---
name: .NET
category: Runtimes
description: .NET, developed by Microsoft, is a versatile, cross-platform framework used for building a wide range of applications. It features a large class library named Framework Class Library (FCL) and provides language interoperability across several programming languages.
download_url: https://dotnet.microsoft.com/en-us/download/dotnet
works_on_arm: true
supported_minimum_version:
  version_number: 5.0
  release_date: 2020/11/10
optional_info:
  homepage_url: https://dotnet.microsoft.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://learn.microsoft.com/en-us/dotnet/core/install/linux-ubuntu
    arm_content: https://learn.arm.com/install-guides/dotnet/
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/dotnet/powering-net-8-with-aws-graviton3-benchmarks/
  arm_recommended_minimum_version:
    version_number: 8.0
    release_date: 2023/10/03
    reference_content: https://devblogs.microsoft.com/dotnet/this-arm64-performance-in-dotnet-8/
    rationale: This version adds various conditional instruction processing optimizations, including conditional comparison, conditional increment, negation, and inversion, vector table lookup APIs, peephole optimizations, and more. Shows performance improvements of up to 50% in select cases.
optional_hidden_info:
  release_notes__supported_minimum: https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-5
  release_notes__recommended_minimum: null
  other_info: null
---
