"dp-service-account": {
    alias: ""
    annotations: {}
    attributes: workload: definition: {
        apiVersion: "apps/v1"
        kind:       "Deployment"
    }
    attributes: {
        status: {
            healthPolicy: #"""
                isHealth: context.output.status.atProvider.associationArn != _|_
            """#
        }
    }
    description: "Service account creation that enables access to cloud resources"
    labels: {}
    type: "component"
}

template: {
    output: {
        apiVersion: "eks.aws.upbound.io/v1beta1"
        kind:       "PodIdentityAssociation"
        metadata: name: "\(context.name)-podidentity"
        spec: {
            forProvider: {
                clusterName: "\(parameter.clusterName)"
                namespace:   "\(context.namespace)"
                region:      "\(parameter.clusterRegion)"
                roleArnRef: name: "\(context.name)-iam-role"
                serviceAccount: "\(context.name)"
            }
        }
    }
    

    outputs: {
        "\(context.name)-iam-role": {
            apiVersion: "iam.aws.upbound.io/v1beta1"
            kind:       "Role"
            metadata: name: "\(context.name)-iam-role"
            spec: {
                forProvider: {
                    assumeRolePolicy: {"""
                          {
                            "Version": "2012-10-17",
                            "Statement": [
                              {
                                "Effect": "Allow",
                                "Principal": {
                                  "Service": "pods.eks.amazonaws.com"
                                },
                                "Action": [
                                  "sts:AssumeRole",
                                  "sts:TagSession"
                                ]
                              }
                            ]
                          }
                        """}
                }
            }
        }

        if parameter.componentNamesForAccess != _|_ {
            for _, c in parameter.componentNamesForAccess {
                let component = context.components["\(c)"]
                if component != _|_ {}
                "\(context.name)-\(c)-iam-policy": {
                    apiVersion: "iam.aws.upbound.io/v1beta1"
                    kind:       "RolePolicyAttachment"
                    metadata: name: "\(context.name)-\(c)-role-policy-attachment"
                    spec: {
                        forProvider: {
                            policyArnRef: name: "\(context.appName)-\(c)-iam-policy"
                            roleRef: name:      "\(context.name)-iam-role"
                        }
                    }
                }
            }
        }

        "\(context.name)-service-account": {
            apiVersion: "v1"
            kind:       "ServiceAccount"
            metadata: name: "\(context.name)"
        }
        
    }

    parameter: {
        // +usage=Specify the components with policies to add to the service account
        componentNamesForAccess?: [...string]
        // +usage=Region cluster is in
        clusterRegion: string
        // +usage=name of the cluster for pod identity
        clusterName: string
    }

}
