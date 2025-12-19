echo Logging in to Amazon ECR...
AWS_REGION=us-west-2
AWS_ACCOUNT_ID=012345678910
ECR_REPOSITORY_NAME=moderneng/northwind
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY_NAME
COMMIT_HASH=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c 1-7)
IMAGE_TAG=${COMMIT_HASH:=latest}
echo Build started on `date`
echo Building the Docker image...
docker build -t $REPOSITORY_URI:latest .
docker tag $REPOSITORY_URI:latest $REPOSITORY_URI:$IMAGE_TAG
echo Build completed on `date`
echo Pushing the Docker images...
docker push $REPOSITORY_URI:$IMAGE_TAG
