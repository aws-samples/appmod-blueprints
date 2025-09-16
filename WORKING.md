trying to make backstage template work with gitlab

interesting files :

- /home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates/catalog-info.yaml
    - if changed, need to reexecute the script /home/ec2-user/environment/platform-on-eks-workshop/scripts/0-install.sh

- original template that is using gitea : /home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates/s3-bucket-ack

- new one that we want to make work with gitlab /home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates/s3-bucket-ack-gitlab