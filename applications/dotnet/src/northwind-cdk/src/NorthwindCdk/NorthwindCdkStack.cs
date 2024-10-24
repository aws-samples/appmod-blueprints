using Amazon.CDK;
using Amazon.CDK.AWS.SNS;
using Amazon.CDK.AWS.SNS.Subscriptions;
using Amazon.CDK.AWS.SQS;
using Constructs;

using Amazon.CDK.AWS.CodeBuild;
using Amazon.CDK.AWS.IAM;
using System.Collections.Generic;

namespace NorthwindCdk
{
    public class NorthwindCdkStack : Stack
    {
        internal NorthwindCdkStack(Construct scope, string id, IStackProps props = null) : base(scope, id, props)
        {

        // Create the CodeBuild project
            Role codeBuildRole  = new Role(this, "CodeBuildRole", new RoleProps
                {
                    AssumedBy = new ServicePrincipal("codebuild.amazonaws.com")
                    
                });
                 // Add managed policies to the role
            codeBuildRole.AddManagedPolicy(ManagedPolicy.FromAwsManagedPolicyName("AmazonEC2ContainerRegistryFullAccess"));
            codeBuildRole.AddManagedPolicy(ManagedPolicy.FromAwsManagedPolicyName("CloudWatchLogsFullAccess"));
            
            Project project = new Project(this, "ModernEnggCB", new ProjectProps
            {
                BuildSpec = BuildSpec.FromAsset("src/buildspec.yml"),
                Environment = new BuildEnvironment
                {
                    BuildImage = LinuxBuildImage.AMAZON_LINUX_2_ARM_2,
                    Privileged = true
                },
                EnvironmentVariables = new Dictionary<string, IBuildEnvironmentVariable>()
                {
                    { "AWS_REGION", new BuildEnvironmentVariable { Type = BuildEnvironmentVariableType.PLAINTEXT, Value = this.Region} },
                    { "AWS_ACCOUNT_ID", new BuildEnvironmentVariable { Type = BuildEnvironmentVariableType.PLAINTEXT, Value = this.Account} },
                    { "GITEA_URL", new BuildEnvironmentVariable { Type = BuildEnvironmentVariableType.PLAINTEXT, Value = "gitea.renukakn.people.aws.dev"} },
                    { "ECR_REPOSITORY_NAME", new BuildEnvironmentVariable { Type = BuildEnvironmentVariableType.PLAINTEXT, Value = "modern_engg"} }
                },
                Role = codeBuildRole
            });
        }

        



    }
}
