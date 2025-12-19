# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
typeset -g POWERLEVEL9K_INSTANT_PROMPT=quiet
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi


export PATH=$PATH:~/Library/Python/3.7/bin:/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin
export GOPATH=~/go
export GOROOT=/usr/local/go
export PATH=~/bin:~/.pyenv/shims:$PATH:/usr/local/sbin:$GOPATH/bin:$GOROOT/bin
export PATH=$PATH:/usr/local/kubebuilder/bin
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH:~/.fzf/bin/"
export PATH=$PATH:/usr/local/aws-codeguru-cli/bin
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"
export PATH=/usr/local/go/bin:~/go/bin:$PATH
# Path to your oh-my-zsh installation.
export ZSH=$HOME/.oh-my-zsh

skip_global_compinit=1
ZSH_DISABLE_COMPFIX=true
DISABLE_UNTRACKED_FILES_DIRTY="true"
HYPHEN_INSENSITIVE="true"
MENU_COMPLETE="true"
DISABLE_UPDATE_PROMPT="true"
ZSH_THEME="powerlevel10k/powerlevel10k"

# Custom plugins may be added to ~/.oh-my-zsh/custom/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(
    git
    docker
    virtualenv
    kubectl
    wd
    helm
    terraform
    zsh-syntax-highlighting
    zsh-autosuggestions
    zsh-history-substring-search
)

export TERM="xterm-256color"

#I don't want to share history between terminals
setopt no_share_history
unsetopt share_history


alias k=kubectl
alias kl='kubectl logs deploy/karpenter -n karpenter -f --tail=20'

alias emacs=emacs-nox
alias kns=kubens
alias kctx=kubectx
source $ZSH/oh-my-zsh.sh

alias python=python3
alias pip=pip3
alias tfi='terraform init'
alias tfp='terraform plan'
alias tfy='terraform apply --auto-approve'

alias eks-node-viewer='eks-node-viewer -extra-labels=karpenter.sh/nodepool,beta.kubernetes.io/arch,topology.kubernetes.io/zone'
alias dfimage="docker run -v /var/run/docker.sock:/var/run/docker.sock --rm ghcr.io/laniksj/dfimage"

fpath=($fpath ~/.zsh/completion)


[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh


[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh


#Specific Seb
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity | jq ".Account" -r)
export ACCOUNT_ID=$AWS_ACCOUNT_ID
export AWS_ACCOUNT=$AWS_ACCOUNT_ID
TOKEN=`curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
export AWS_DEFAULT_REGION=$( curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/dynamic/instance-identity/document | jq ".region" -r )
export AWS_REGION=$AWS_DEFAULT_REGION
export CDK_DEFAULT_REGION=$AWS_REGION
export CDK_DEFAULT_ACCOUNT=$AWS_ACCOUNT_ID

alias kns=kubens
alias kctx=kubectx
alias kgn='kubectl get nodes -L beta.kubernetes.io/arch -L eks.amazonaws.com/capacityType -L karpenter.sh/capacity-type -L node-lifecycle -L beta.kubernetes.io/instance-type -L eks.amazonaws.com/nodegroup -L topology.kubernetes.io/zone -L karpenter.sh/provisioner-name'
alias wkgn='watch kubectl get nodes -L beta.kubernetes.io/arch -L eks.amazonaws.com/capacityType -L karpenter.sh/capacity-type -L node-lifecycle -L beta.kubernetes.io/instance-type -L eks.amazonaws.com/nodegroup -L topology.kubernetes.io/zone -L karpenter.sh/provisioner-name'

alias kgall='kubectl api-resources --verbs=list --namespaced -o name | xargs -n 1 kubectl get --show-kind --ignore-not-found'

function assume_aws_role() {
  # Read role ARN from the file
  PLATFORM_ROLE_ARN=$1
  echo "PLATFORM_ROLE_ARN is $PLATFORM_ROLE_ARN"

  # Assume the role
  CREDENTIALS=$(aws sts assume-role --duration-seconds 3600 --role-arn "$PLATFORM_ROLE_ARN" --role-session-name eks)
  # Set the AWS credentials as environment variables
  export AWS_ACCESS_KEY_ID=$(echo "$CREDENTIALS" | jq -r '.Credentials.AccessKeyId')
  export AWS_SECRET_ACCESS_KEY=$(echo "$CREDENTIALS" | jq -r '.Credentials.SecretAccessKey')
  export AWS_SESSION_TOKEN=$(echo "$CREDENTIALS" | jq -r '.Credentials.SessionToken')
  export AWS_EXPIRATION=$(echo "$CREDENTIALS" | jq -r '.Credentials.Expiration')

  # Verify the AWS identity after assuming the role
  aws sts get-caller-identity
}

alias list-vpc="aws ec2 --output text --query 'Vpcs[*].{VpcId:VpcId,Name:Tags[?Key==\`Name\`].Value|[0],CidrBlock:CidrBlock}' describe-vpcs"

function lolbanner {
  figlet -c -f ~/.local/share/fonts/figlet-fonts/3d.flf $@ | lolcat
}

export PATH="/usr/local/opt/gnu-getopt/bin:$PATH"
#kubectx and kubens
export PATH=~/.kubectx:$PATH

#get ride of escaping when pasting {} :https://github.com/ohmyzsh/ohmyzsh/issues/6654
#zstyle ':urlglobber' url-other-schema
# or (before OMZ is sourced)
DISABLE_MAGIC_FUNCTIONS=true


alias ecr-public-auth='aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws'
alias ecr-auth='aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin $ECR_REPO'

alias logs-external-dns='kubectl logs -n external-dns -l app.kubernetes.io/name=external-dns -f'

alias netshoot='kubectl run tmp-shell --rm -i --tty --image nicolaka/netshoot'

alias ll='ls -la'
alias pj='npx projen'
alias code=/usr/lib/code-server/bin/code-server

export LANG=en_US.UTF-8

autoload -U +X bashcompinit && bashcompinit
complete -o nospace -C /usr/bin/terraform terraform
[[ -s ~/bin/env-vars.sh ]] && source ~/bin/env-vars.sh

#AWS completion
autoload bashcompinit && bashcompinit
autoload -Uz compinit && compinit
complete -C '/usr/local/bin/aws_completer' aws

#Activate direnv
eval "$(direnv hook zsh)"

source <(kubectl completion zsh)

# User specific aliases and functions
if [ -d ~/.bashrc.d ]; then
        for rc in ~/.bashrc.d/*; do
                if [ -f "$rc" ]; then
                        . "$rc"
                fi
        done
fi