#!/bin/bash

# Setup pre-commit hooks for the appmod-blueprints repository

echo "Setting up pre-commit hooks for appmod-blueprints..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "pre-commit is not installed. Installing via pip..."
    pip install pre-commit
fi

# Install the git hook scripts
pre-commit install

echo "Pre-commit hooks installed successfully!"
echo ""
echo "The following checks will run on commit:"
echo "- Trailing whitespace removal"
echo "- End of file fixer"
echo "- YAML syntax check"
echo "- Large files check"
echo "- Merge conflict check"
echo "- Backstage TypeScript type checking"
echo "- Terraform format checking"
echo ""
echo "To run checks manually: pre-commit run --all-files"