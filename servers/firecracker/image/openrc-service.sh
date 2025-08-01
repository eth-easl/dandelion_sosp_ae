#!/sbin/openrc-run

name=$RC_SVCNAME
description="Function agent"
supervisor="supervise-daemon"
command="/usr/local/bin/agent"
pidfile="/run/agent.pid"
command_user="agentUser:agentUser"
output_log="/tmp/agent.log"
error_log="/tmp/agent.err"
depend() {
	after net
}
# TODO set this dynamically
export STORAGE_HOST="10.10.1.1:8000"
