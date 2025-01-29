# S3 to Lambda

This pattern demonstrates a [S3 to Lambda](https://github.com/aws-samples/appmod-partners-serverless/tree/main/tf-patterns/s3-lambda-terraform) pattern.

## Prerequisite

You need to [add AWS credentials](https://github.com/tgpadua/backstage-terraform-integrations/tree/main?tab=readme-ov-file#deploy-idpbuilder-with-terraform-integration-templates) before deployed this pattern. 

## Deployment

Navigate to [Backstage](https://cnoe.localtest.me:8443/), click on `Create` in the left pane to view the list of available platform templates, and click `Choose` on the **S3 Lambda Terraform** pattern.

Next, populate the Terraform variables for the pattern deployment as shown below and click on `Review`.

![Backstage](../../images/s3-lambda-terraform/backstage1.png)

Next, validate the entered variables in the below confirmation screen and click Create :

![Backstage](../../images/s3-lambda-terraform/backstage2.png)

Next, check on the steps of backstage template run as show below and click `Open In Catalog`:

![Backstage](../../images/s3-lambda-terraform/backstage3.png)

Next, check on the below screen showing the created Backstage component and click `View Source` to navigate to the Gitea repository:

![Backstage](../../images/s3-lambda-terraform/backstage4.png)

Next, check on the Gitea repo of the created component as shown below:

![Backstage](../../images/s3-lambda-terraform/gitea1.png)

Next, Navigate to [ArgoCD](https://cnoe.localtest.me:8443/argocd) console and navigate to Argo App by name `dinosaur` view the below screen:

![Backstage](../../images/s3-lambda-terraform/argocd1.png)

## Testing

Please refer to the [pattern](https://github.com/aws-samples/appmod-partners-serverless/tree/main/tf-patterns/s3-lambda-terraform) to see how this pattern works and can be tested.

## Clean up

To clean up all the resources created please follow these steps:

1. In your [Argo CD](https://cnoe.localtest.me:8443/argocd) console, navigate to the application created for your component and click on delete.
2. In your [Gitea](https://cnoe.localtest.me:8443/gitea/) console, navigate to the repository for your component and delete it manually under settings. 
3. Finally, in your [Backstage](https://cnoe.localtest.me:8443/) console, navigate to component created and click on `unregister component`.


