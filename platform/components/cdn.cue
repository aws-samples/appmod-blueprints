"cloudfront-distribution": {
	alias: "cdn"
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "aws-service/v1"
		kind:       "cdn"
	}
	description: "AWS CloudFront distribution customized for serving images from S3"
	labels: {}
	type: "component"
	parameter: {
		region: string
	}
}

template: {
	output: {
		apiVersion: "aws.crossplane.io/v1beta1"
		kind:       "Composition"
		metadata: {
			name: "s3-cloudfront-distribution"
		}
		spec: {
			compositeTypeRef: {
				apiVersion: "aws-service/v1"
				kind:       "CDN"
			}
			resources: [
				{
					name: "s3-bucket"
					base: {
						apiVersion: "s3.aws.crossplane.io/v1beta1"
						kind:       "Bucket"
						spec: {
							forProvider: {
								acl:    "private"
								region: parameter.region
							}
							providerConfigRef: {
								name: "aws-provider"
							}
						}
					}
				},
				{
					name: "origin-access-identity"
					base: {
						apiVersion: "cloudfront.aws.crossplane.io/v1alpha1"
						kind:       "CloudFrontOriginAccessIdentity"
						spec: {
							forProvider: {
								comment: "OAI for S3 bucket access"
							}
							providerConfigRef: {
								name: "aws-provider"
							}
						}
					}
				},
				{
					name: "cloudfront-distribution"
					base: {
						apiVersion: "cloudfront.aws.crossplane.io/v1alpha1"
						kind:       "Distribution"
						spec: {
							forProvider: {
								distributionConfig: {
									enabled:       true
									httpVersion:   "http2"
									isIPV6Enabled: true
									origins: [{
										domainName: "\($.resources[0].status.atProvider.regionDomainName)"
										id:         "S3Origin"
										s3OriginConfig: {
											originAccessIdentity: "\($.resources[1].status.atProvider.id)"
										}
									}]
									defaultCacheBehavior: {
										allowedMethods: [
											"GET",
											"HEAD",
										]
										cachedMethods: [
											"GET",
											"HEAD",
										]
										targetOriginId:       "S3Origin"
										viewerProtocolPolicy: "redirect-to-https"
										minTTL:               0
										defaultTTL:           3600
										maxTTL:               86400
										compress:             true
										forwardedValues: {
											queryString: false
											cookies: {
												forward: "none"
											}
										}
									}
									viewerCertificate: {
										cloudFrontDefaultCertificate: true
									}
								}
							}
							providerConfigRef: {
								name: "aws-provider"
							}
						}
					}
				},
				{
					name: "s3-bucket-policy"
					base: {
						apiVersion: "s3.aws.crossplane.io/v1beta1"
						kind:       "BucketPolicy"
						spec: {
							forProvider: {
								region:     parameter.region
								bucketName: "\($.resources[0].status.atProvider.name)"
								policy: json.Marshal({
									Version: "2008-10-17"
									Id:      "PolicyForCloudFrontPrivateContent"
									Statement: [
										{
											Sid:    "AllowCloudFrontServicePrincipal"
											Effect: "Allow"
											Principal: Service: "cloudfront.amazonaws.com"
											Action:   "s3:GetObject"
											Resource: "arn:aws:s3:::\($.resources[0].status.atProvider.name)/*"
											Condition: StringEquals: "AWS:SourceArn": "\($.resources[2].status.atProvider.arn)"
										},
									]
								})
							}
							providerConfigRef: {
								name: "aws-provider"
							}
						}
					}
				},
			]
		}
	}
}
