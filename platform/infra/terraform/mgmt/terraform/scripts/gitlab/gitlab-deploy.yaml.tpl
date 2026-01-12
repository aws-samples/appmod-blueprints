apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.eks.amazonaws.com
volumeBindingMode: WaitForFirstConsumer
parameters:
  type: gp3
  encrypted: "true"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: gitlab-data
  namespace: gitlab
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: gp3
  resources:
    requests:
      storage: 50Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gitlab
  namespace: gitlab
spec:
  selector:
    matchLabels:
      app: gitlab
  strategy:
    type: Recreate
  replicas: 1
  template:
    metadata:
      labels:
        app: gitlab
    spec:
      volumes:
      - name: gitlab-data
        persistentVolumeClaim:
          claimName: gitlab-data
      - name: gitlab-config
        secret:
          secretName: gitlab-config
      containers:
      - name: gitlab
        image: gitlab/gitlab-ce:latest
        ports:
        - containerPort: 80
          name: http
        # - containerPort: 443
        #   name: https
        - containerPort: 22
          name: ssh
        env:
        - name: GITLAB_OMNIBUS_CONFIG
          value: |
            external_url 'http://GITLAB_DOMAIN_NAME'
            gitlab_rails['gitlab_shell_ssh_port'] = 22
            gitlab_rails['gitlab_shell_git_timeout'] = 800
            gitlab_rails['enabled_git_access_protocol'] = 'ssh'

            # Disable Let's Encrypt
            letsencrypt['enable'] = false

            # Disable HTTPS
            nginx['ssl_certificate'] = nil
            nginx['ssl_certificate_key'] = nil
            nginx['redirect_http_to_https'] = false
            nginx['listen_https'] = false

            # Disable Prometheus monitoring
            prometheus_monitoring['enable'] = false

            # Disable CI/CD features
            # gitlab_ci['enable'] = false
            # gitlab_rails['gitlab_default_projects_features_builds'] = false

            # Disable container registry
            registry['enable'] = false
            registry_nginx['enable'] = false

            # Disable pages
            pages_enabled = false
            gitlab_pages['enable'] = false

            # Disable monitoring features
            alertmanager['enable'] = false
            node_exporter['enable'] = false
            redis_exporter['enable'] = false
            postgres_exporter['enable'] = false

            # Disable Mattermost
            mattermost['enable'] = false
            mattermost_nginx['enable'] = false

            # Disable Kubernetes integration
            # gitlab_kas['enable'] = false

            # Disable SMTP if not needed
            gitlab_rails['smtp_enable'] = false

            # Disable Sidekiq metrics
            sidekiq['metrics_enabled'] = false

            # Puma
            puma['worker_processes'] = 0
            puma['per_worker_max_memory_mb'] = 1024

            # Reduce Redis resources
            redis['tcp_timeout'] = 60
            redis['tcp_keepalive'] = 300

            # # Optional: Disable features at project level
            # gitlab_rails['gitlab_default_projects_features'] = {
            #   'issues' => true,
            #   'merge_requests' => true,
            #   'wiki' => false,
            #   'snippets' => false,
            #   'builds' => true,
            #   'container_registry' => false
            # }

            # Reduce Sidekiq concurrency
            sidekiq['concurrency'] = 5
            gitlab_rails['monitoring_whitelist'] = ['0.0.0.0/0']
            gitlab_rails['signup_enabled'] = false
            gitlab_rails['initial_root_password'] = 'GITLAB_PASSWORD'
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "4Gi"
            cpu: "2"
        securityContext:
          privileged: false
          runAsUser: 0
        livenessProbe:
          httpGet:
            path: /-/liveness
            port: 80
          initialDelaySeconds: 180
          timeoutSeconds: 15
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /-/readiness
            port: 80
          initialDelaySeconds: 180
          timeoutSeconds: 15
          periodSeconds: 30
        volumeMounts:
        - name: gitlab-data
          mountPath: /etc/gitlab
          subPath: config
        - name: gitlab-data
          mountPath: /var/log/gitlab
          subPath: logs
        - name: gitlab-data
          mountPath: /var/opt/gitlab
          subPath: data
---
# RBAC resources for GitLab initialization
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: gitlab
  name: gitlab-init-role
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gitlab-init-rolebinding
  namespace: gitlab
subjects:
- kind: ServiceAccount
  name: default
  namespace: gitlab
roleRef:
  kind: Role
  name: gitlab-init-role
  apiGroup: rbac.authorization.k8s.io
---
# ConfigMap for initialization script
apiVersion: v1
kind: ConfigMap
metadata:
  name: gitlab-init-script
  namespace: gitlab
data:
  init-gitlab.sh: |
    #!/bin/bash
    set -e

    # Wait for GitLab to be ready
    echo "Waiting for GitLab to be ready..."
    until curl -s --head --fail http://GITLAB_DOMAIN_NAME/-/readiness; do
      echo "GitLab not ready yet, waiting..."
      sleep 10
    done

    # Set variables
    export GITLAB_URL=http://GITLAB_DOMAIN_NAME
    export GITLAB_POD_NAME=$(kubectl get pods -n gitlab -l app=gitlab -o jsonpath='{.items[0].metadata.name}')
    export ROOT_GITLAB_TOKEN="root-GITLAB_PASSWORD"
    export IDE_PASSWORD="GITLAB_PASSWORD"
    export GIT_USERNAME="user1"
    export WORKING_REPO="appmod-blueprints"

    # Clone appmod-blueprints github repo
    git clone https://github.com/aws-samples/appmod-blueprints.git /app/appmod-blueprints


    # Check if root token already exists
    echo "Checking if root token already exists..."
    TOKEN_EXISTS=$(kubectl exec -it $GITLAB_POD_NAME -n gitlab -- gitlab-rails runner "puts User.find_by_username('root').personal_access_tokens.where(name: 'initial root token').exists?" || echo "false")

    if [[ "$TOKEN_EXISTS" != "true" ]]; then
      echo "Creating GitLab API token for root..."
      kubectl exec -it $GITLAB_POD_NAME -n gitlab -- gitlab-rails runner "
        token = User.find_by_username('root').personal_access_tokens.create(
          name: 'initial root token',
          scopes: [
            'api',
            'read_user',
            'read_repository',
            'write_repository',
            'sudo',
            'admin_mode'
          ],
          expires_at: 365.days.from_now
        )
        token.set_token('${ROOT_GITLAB_TOKEN}')
        token.save!
      "
    else
      echo "Root token already exists, skipping creation."
    fi

    # Update GitLab settings
    echo "Updating GitLab settings..."
    kubectl exec -it $GITLAB_POD_NAME -n gitlab -- gitlab-rails runner '::Gitlab::CurrentSettings.update!(signup_enabled: false)'

    # Check if user already exists
    echo "Checking if user $GIT_USERNAME already exists..."
    USER_EXISTS=$(curl -s "$GITLAB_URL/api/v4/users?search=$GIT_USERNAME" -H "PRIVATE-TOKEN: $ROOT_GITLAB_TOKEN" | jq -r 'length')

    if [[ "$USER_EXISTS" == "0" ]]; then
      echo "Creating $GIT_USERNAME..."
      curl -sS -X 'POST' "$GITLAB_URL/api/v4/users" \
        -H "PRIVATE-TOKEN: $ROOT_GITLAB_TOKEN" \
        -H 'accept: application/json' \
        -H 'Content-Type: application/json' \
        -d "{
        \"name\": \"$GIT_USERNAME\",
        \"username\": \"$GIT_USERNAME\",
        \"email\": \"$GIT_USERNAME@example.com\",
        \"password\": \"$IDE_PASSWORD\"
      }" && echo -e "\n"

      echo "Creating GitLab API token for $GIT_USERNAME..."
      kubectl exec -it $GITLAB_POD_NAME -n gitlab -- gitlab-rails runner "
        token = User.find_by_username('$GIT_USERNAME').personal_access_tokens.create(
          name: 'initial $GIT_USERNAME token',
          scopes: [
            'api',
            'read_user',
            'read_repository',
            'write_repository'
          ],
          expires_at: 365.days.from_now
        )
        token.set_token('${IDE_PASSWORD}')
        token.save!
      "
    else
      echo "User $GIT_USERNAME already exists, skipping creation."
    fi

    # Check if repository already exists
    echo "Checking if repository $WORKING_REPO already exists..."
    REPO_EXISTS=$(curl -s "$GITLAB_URL/api/v4/projects?search=$WORKING_REPO" -H "PRIVATE-TOKEN: $IDE_PASSWORD" | jq -r 'length')

    if [[ "$REPO_EXISTS" == "0" ]]; then
      echo "Creating $WORKING_REPO Git repository..."
      curl -Ss -X 'POST' "$GITLAB_URL/api/v4/projects/" \
        -H "PRIVATE-TOKEN: $IDE_PASSWORD" \
        -H 'accept: application/json' \
        -H 'Content-Type: application/json' \
        -d "{
        \"name\": \"$WORKING_REPO\"
      }" && echo -e "\n"
    else
      echo "Repository $WORKING_REPO already exists, skipping creation."
    fi

    # Check if repo exists or not
    check_repo_exist() {
      local repo_name=$1
      REPO_EXISTS=$(curl -s "$GITLAB_URL/api/v4/projects?search=$repo_name" -H "PRIVATE-TOKEN: $IDE_PASSWORD" | jq -r 'length')
      if [[ "$REPO_EXISTS" == "0" ]]; then
        echo "Repository $repo_name does not exist."
        return 1
      else
        echo "Repository $repo_name exists."
        return 0
      fi
    }

    # Create repository
    check_and_create_repo() {
      local repo_name=$1
      if check_repo_exist "$repo_name"; then
        echo "Repository $repo_name already exists, skipping creation."
      else
        echo "Creating $repo_name Git repository..."
        curl -Ss -X 'POST' "$GITLAB_URL/api/v4/projects/" \
          -H "PRIVATE-TOKEN: $IDE_PASSWORD" \
          -H 'accept: application/json' \
          -H 'Content-Type: application/json' \
          -d "{
          \"name\": \"$repo_name\"
        }" && echo -e "\n"
      fi
      # Pushing content to repos
      create_repo_content_application $repo_name
    }

    create_repo_content_application() {
      local repo_name=$1
      local GILAB_REPO_URL="http://$GIT_USERNAME:$IDE_PASSWORD@GITLAB_DOMAIN_NAME/$GIT_USERNAME/$repo_name.git"
      local repo_root="/apps/applications/gitlab"
      
      echo "Creating initial repo content for $repo_name..."
      rm -rf $repo_root
      mkdir -p $repo_root
      git clone $GILAB_REPO_URL $repo_root/$repo_name
      pushd $repo_root/$repo_name
      git config user.email "participants@workshops.aws"
      git config user.name "Workshop Participant"

      if [[ "$repo_name" == "platform" ]]; then
        cp -r /app/appmod-blueprints/deployment/addons/kubevela $repo_root/$repo_name/
        cp -r /app/appmod-blueprints/platform/backstage $repo_root/$repo_name/
        # Replacing hostname in backstage catalog file
        sed -i "s/HOSTNAME/GITLAB_DOMAIN_NAME/g" $repo_root/$repo_name/backstage/templates/catalog-info.yaml
      elif [[ "$repo_name" == "terraform-eks" ]]; then
        cp -r /app/appmod-blueprints/platform/infra/terraform/dev $repo_root/$repo_name/
        cp -r /app/appmod-blueprints/platform/infra/terraform/prod $repo_root/$repo_name/
        # Added for Aurora and DB Setup
        cp -r /app/appmod-blueprints/platform/infra/terraform/database $repo_root/$repo_name/
        cp /app/appmod-blueprints/platform/infra/terraform/.gitignore $repo_root/$repo_name/
        cp /app/appmod-blueprints/platform/infra/terraform/create-cluster.sh  $repo_root/$repo_name/
        cp /app/appmod-blueprints/platform/infra/terraform/create-database.sh $repo_root/$repo_name/
      else
        cp -r /app/appmod-blueprints/applications/$repo_name $repo_root
      fi
      git add . || echo "No changes to add"
      git commit -m "first commit" || echo "No changes to commit"
      git remote remove origin
      git remote add origin $GILAB_REPO_URL
      git push -u origin main || echo "Failed to push to $GILAB_REPO_URL"
      popd
    }

    check_and_create_repo "dotnet"
    check_and_create_repo "golang"
    check_and_create_repo "java"
    check_and_create_repo "rust"
    check_and_create_repo "next-js"
    check_and_create_repo "terraform-eks"
    check_and_create_repo "platform"

    echo "GitLab initialization completed successfully."
---
# Initialization Job
apiVersion: batch/v1
kind: Job
metadata:
  name: gitlab-init
  namespace: gitlab
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  backoffLimit: 5
  ttlSecondsAfterFinished: 600
  template:
    metadata:
      name: gitlab-init
    spec:
      serviceAccountName: default
      restartPolicy: OnFailure
      containers:
      - name: gitlab-init
        image: alpine/k8s:1.32.5
        command:
        - /bin/bash
        - -c
        - /scripts/init-gitlab.sh
        volumeMounts:
        - name: init-script
          mountPath: /scripts
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "200m"
      volumes:
      - name: init-script
        configMap:
          name: gitlab-init-script
          defaultMode: 0755