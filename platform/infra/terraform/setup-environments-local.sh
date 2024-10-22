AWS_REGION=$(aws configure get region)
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_ACCOUNT_ARN=$(aws sts get-caller-identity --query Arn --output text)
IAM_USER_NAME="modern-engg-local-test-user"
ROLE_NAME="developer-env-VSCodeInstanceRole"
ROLE_MAX_SESSION_DURATION=43200
SESSION_DURATION=18000
SESSION_NAME="workshop"

if ! aws iam get-user --user-name "$IAM_USER_NAME" &>/dev/null; then
  aws iam create-user --user-name "$IAM_USER_NAME"
  ACCESS_KEY_OUTPUT=$(aws iam create-access-key --user-name "$IAM_USER_NAME")
  USER_ACCESS_KEY_ID=$(echo $ACCESS_KEY_OUTPUT | jq -r '.AccessKey.AccessKeyId')
  USER_SECRET_ACCESS_KEY=$(echo $ACCESS_KEY_OUTPUT | jq -r '.AccessKey.SecretAccessKey')
  echo "export AWS_ACCESS_KEY_ID=$USER_ACCESS_KEY_ID" >"$IAM_USER_NAME.creds"
  echo "export AWS_SECRET_ACCESS_KEY=$USER_SECRET_ACCESS_KEY" >>"$IAM_USER_NAME.creds"

  echo "IAM user $IAM_USER_NAME created, sleeping"
  sleep 30
else
  echo "IAM user $IAM_USER_NAME already exists, skipping creation"
fi

if ! aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  cat <<EOF >assume-role-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::$AWS_ACCOUNT_ID:user/$IAM_USER_NAME",
          "$AWS_ACCOUNT_ARN"
        ],
        "Service": [
          "ec2.amazonaws.com",
          "ssm.amazonaws.com",
          "codecommit.amazonaws.com",
          "codebuild.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

  aws iam create-role \
    --role-name $ROLE_NAME \
    --assume-role-policy-document file://assume-role-policy.json \
    --max-session-duration $ROLE_MAX_SESSION_DURATION

  aws iam attach-role-policy \
    --role-name $ROLE_NAME \
    --policy-arn "arn:aws:iam::aws:policy/AdministratorAccess"

  cat <<EOF >cdk-assume-role-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/cdk-*"
    }
  ]
}
EOF

  aws iam put-role-policy \
    --role-name $ROLE_NAME \
    --policy-name CDKAssumeRolePolicy-$AWS_REGION \
    --policy-document file://cdk-assume-role-policy.json

  cat <<EOF >codewhisperer-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "codewhisperer:GenerateRecommendations",
      "Resource": "*"
    }
  ]
}
EOF

  aws iam put-role-policy \
    --role-name $ROLE_NAME \
    --policy-name Codewhisperer-$AWS_REGION \
    --policy-document file://codewhisperer-policy.json

  rm codewhisperer-policy.json
  rm cdk-assume-role-policy.json
  rm assume-role-policy.json

  echo "Sleeping to let role populate"
  sleep 60
else
  echo "Role '$ROLE_NAME' already exists, skipping creation."
fi

unset AWS_SESSION_TOKEN

source "$IAM_USER_NAME.creds"
export AWS_ACCESS_KEY_ID=$USER_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$USER_SECRET_ACCESS_KEY
echo $(aws sts get-caller-identity)

ASSUME_ROLE_OUTPUT=$(aws sts assume-role --role-arn arn:aws:iam::${AWS_ACCOUNT_ID}:role/$ROLE_NAME --role-session-name $SESSION_NAME --duration-seconds $SESSION_DURATION)
export AWS_ACCESS_KEY_ID=$(echo $ASSUME_ROLE_OUTPUT | jq -r '.Credentials.AccessKeyId')
export AWS_SECRET_ACCESS_KEY=$(echo $ASSUME_ROLE_OUTPUT | jq -r '.Credentials.SecretAccessKey')
export AWS_SESSION_TOKEN=$(echo $ASSUME_ROLE_OUTPUT | jq -r '.Credentials.SessionToken')

echo "Running script with assumed role credentials"
echo $(aws sts get-caller-identity)

./setup-environments.sh
