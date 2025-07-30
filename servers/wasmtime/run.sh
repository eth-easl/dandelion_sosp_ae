#!/bin/bash

DEFAULT_PORT=8080
DEFAULT_HTTP_STORAGE_PORT=8000
DEFAULT_POOLING=true
DEFAULT_INSTANCES=1000

WASMTIME_EXP_PATH=$1
HTTP_STORAGE_IP=$2

# Check if a port argument is provided
if [ -z "$3" ]; then
    PORT=$DEFAULT_PORT
    echo "No port specified. Using default port: $PORT"
else
    PORT=$3
    echo "Using specified port: $PORT"
fi

# Check if pooling argument is provided
if [ -z "$4" ]; then
    POOLING=$DEFAULT_POOLING
    echo "No pooling argument specified. Using default: pooling enabled."
else
    if [ "$4" == "--disable-pooling" ]; then
        POOLING=false
        echo "Using on-demand allocation strategy (pooling disabled)."
    elif [ "$4" == "--enable-pooling" ]; then
        POOLING=true
        echo "Using pooling allocation strategy (pooling enabled)."
    else
        echo "Invalid argument for pooling: $4. Expected '--disable-pooling', '--enable-pooling', or no argument."
        exit 1
    fi
fi

if [ "$POOLING" = true ]; then
    if [ -z "$5" ]; then
        INSTANCES=$DEFAULT_INSTANCES
        echo "No number of instances specified. Using default: $INSTANCES instances."
    else
        INSTANCES=$5
        echo "Using specified number of instances for pooling: $INSTANCES instances."
    fi
fi

# Check if spin is installed
if ! command -v spin &> /dev/null; then
    echo "Error: Spin CLI is not installed. Please install it first."
    exit 1
fi

# Start the Spin application
export SPIN_VARIABLE_STORAGE_IP="$HTTP_STORAGE_IP:$DEFAULT_HTTP_STORAGE_PORT"
if [ "$POOLING" = true ]; then
    echo "Starting the Spin application with pooling enabled ($INSTANCES instances) on port $PORT..."
    spin up -f "$WASMTIME_EXP_PATH" --listen 0.0.0.0:$PORT --env SPIN_WASMTIME_INSTANCE_COUNT=$INSTANCES
else
    echo "Starting the Spin application with pooling disabled on port $PORT..."
    spin up -f "$WASMTIME_EXP_PATH" --listen 0.0.0.0:$PORT --disable-pooling
fi

if [ $? -ne 0 ]; then
    echo "Error: Spin up failed. Please check your application logs."
    exit 1
fi
