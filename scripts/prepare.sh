#!/bin/bash

# Function to display usage information
usage() {
    echo "Usage: $0 env_file [command...]"
    echo "The conda environment name will be read from CONDA_ENV_NAME in the env file"
    echo "env_file is required and must be provided as the first argument"
    echo "Any additional arguments will be executed as a command after activating the environment"
    exit 1
}

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if at least one command-line argument was provided to specify the env file
if [ $# -lt 1 ]; then
    echo "Error: Environment file must be provided as the first argument"
    usage
fi

# Set the environment file from the first argument
ENV_FILE="$1"
# Shift the arguments to remove the env file argument
shift

# Source the env file if it exists (for all environment variables)
if [ -f "$SCRIPT_DIR/$ENV_FILE" ]; then
    echo "Using environment file: $ENV_FILE"
    set -a  # automatically export all variables
    source "$SCRIPT_DIR/$ENV_FILE"
    set +a  # disable auto-export
elif [ -f "$ENV_FILE" ]; then
      echo "Using environment file: $ENV_FILE"
    set -a  # automatically export all variables
    source "$ENV_FILE"
    set +a
else
    echo "Error: $ENV_FILE file not found in $SCRIPT_DIR"
    exit 1
fi

# Check if CONDA_ENV_NAME is set in the env file
if [ -z "$CONDA_ENV_NAME" ]; then
    echo "Warning: CONDA_ENV_NAME is not set in $ENV_FILE. Skipping conda environment activation."
else
    # Initialize conda
    eval "$(~/miniconda3/bin/conda shell.bash hook)"

    # Activate the conda environment
    echo "Activating conda environment: $CONDA_ENV_NAME"
    conda activate "$CONDA_ENV_NAME"
fi

# Handle PYTHONPATH_DIRS if specified in the env file
if [ -n "$PYTHONPATH_DIRS" ]; then
    echo "Adding directories to PYTHONPATH: $PYTHONPATH_DIRS"
    # Convert colon-separated list to array
    IFS=':' read -ra DIRS <<< "$PYTHONPATH_DIRS"

    # Prepend each directory to PYTHONPATH
    for dir in "${DIRS[@]}"; do
        # Check if directory exists
        if [ -d "$dir" ]; then
            export PYTHONPATH="$dir:$PYTHONPATH"
        else
            echo "Warning: Directory $dir does not exist, skipping"
        fi
    done
    echo "PYTHONPATH is now: $PYTHONPATH"
fi

# Execute any additional arguments as a command if provided
if [ $# -gt 0 ]; then
    echo "Running command: $@"
    "$@"
fi