import socket
import subprocess
import json
import os
import time
from datetime import datetime
import sys

import requests

# Path to the log file
log_file_path = '/opt/prometheus_monitor/check_status.log'
hostname = socket.gethostname()
if "logic" in hostname :
    app_name = 'logic'
    file_name = 'com.typesafe.slick.slick_2.12-3.2.0.jar'
    folder_name = 'logic'

# Python 2 and 3 compatibility for print function
try:
    input = raw_input  # Python 2 compatibility for input function
except NameError:
    pass

# Log errors to a file
def log_error(message):
    with open(log_file_path, 'w') as log_file:
        log_file.write("{}: {}\n".format(datetime.now(), message))

def get_app_status():
    try:
        # Execute the command to check the application's status
        result = subprocess.run(
            ["/etc/init.d/{}".format(app_name), "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False  # Do not raise an exception for non-zero exit codes
        )

        # Check if the output indicates the process is running
        if "process is running." in result.stderr.lower():  # Check stderr for the running status
            return 1  # Application is running
        else:
            return 0  # Application is not running

    except Exception as e:
        # Handle any other exceptions
        print(f"Error in get_app_status: {e}")  # Print any errors
        return 0  # Return 0 on any exception
def check_druid_health():
    url = "http://localhost:8000/status/health"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            # Directly check if the response text is 'true'
            if response.text.strip().lower() == "true":
                return 1
        return 0
    except Exception as e:
        print(f"Error occurred: {e}")
        return 0

def check_port_status(port):
    """Checks if a port is open and in use."""
    try:
        result = subprocess.Popen(["ss", "-tuln"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, _ = result.communicate()
        return 1 if ":{}".format(port) in output.decode('utf-8') else 0
    except Exception as e:
        log_error("Error in check_port_status: {}".format(e))
        return 0

def find_executable(executable):

    """Finds the full path to an executable by searching the system PATH."""

    paths = os.environ.get("PATH", "").split(os.pathsep)

    for path in paths:

        full_path = os.path.join(path.strip("\""), executable)

        if os.path.isfile(full_path) and os.access(full_path, os.X_OK):

            return full_path
    return None

def count_iptables_rows():

    """Counts the number of iptables rows."""

    try:
        # Dynamically find the path to iptables
        iptables_path = find_executable("iptables")
        if not iptables_path:
            log_error("iptables command not found in PATH.")
            return 0
        # Run iptables command
        iptables_output = subprocess.check_output(
            ["sudo", iptables_path, "-L"],
            stderr=subprocess.STDOUT
        )
        # Decode output to string (handles both Python 2 and 3)
        if not isinstance(iptables_output, str):
            iptables_output = iptables_output.decode("utf-8")
        # Count the number of non-empty lines
        lines = [line for line in iptables_output.splitlines() if line.strip()]
        return len(lines)
    except subprocess.CalledProcessError as e:
        log_error("Error in count_iptables_rows: {}".format(e))
        return 0
    except Exception as e:
        log_error("Unexpected error in count_iptables_rows: {}".format(e))
        return 0
def check_iptables_content():
    """Checks the content of iptables rules."""
    try:
        with open('/etc/iptables/rules.v4') as f:
            content = f.read()
            return 1 if "Prometheus on port 9100" in content else 0
    except Exception as e:
        log_error("Error in check_iptables_content: {}".format(e))
        return 0

def file_age(filepath):
    """Returns the age of a file in the specified unit (minutes, hours, or days)."""
    real_filepath = os.path.realpath(filepath)
    current_time = time.time()
    try:
        file_mod_time = os.path.getmtime(real_filepath)
    except (OSError, Exception) as e:
        log_error("Error in file_age: {}".format(e))
        return -1

    age_seconds = current_time - file_mod_time
    return round(age_seconds)


def check_service_status(service_name):
    """Checks if a service is active."""
    try:
        result = subprocess.check_output(['systemctl', 'is-active', service_name], stderr=subprocess.STDOUT)
        if hasattr(result, 'decode'):
            status = result.decode('utf-8').strip()  # Python 3 decode
        else:
            status = result.strip()  # Python 2 strip directly
        return 1 if status == 'active' else 0
    except subprocess.CalledProcessError:
        return 0
    except Exception as e:
        log_error("Error in check_service_status: {}".format(e))
        return 0


def check_connectivity(host, port, timeout=5):
    """Checks if a connection can be established to a host on a given port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)

    try:
        s.connect((host, port))
        s.shutdown(socket.SHUT_RDWR)
        return 1
    except socket.timeout:
        log_error("Timeout on port {} at {}".format(port, host))
    except socket.error as e:
        log_error("Timeout on port {} at {}".format(port, host))
    finally:
        s.close()
    return 0

def test_logic_scala(port=80, healthcheck_url="http://localhost/srv/logic/?hash=l6ef5a"):
    # Initialize status to 0 (not healthy)
    status = 0

    # Check if the specified port is open
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('localhost', port)) == 0:
            try:
                # Check if the health check URL returns '1'
                response = requests.get(healthcheck_url)
                if response.text == "1":
                    status = 1  # Both port is open and health check returned 1
            except requests.RequestException:
                pass  # Handle any request errors silently
        else:
            print(f"Port {port} is not open.")

    return status

# Load the configuration from the selected *-monitor.json
def load_configuration(config_file_path):
    try:
        with open(config_file_path, 'r') as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log_error("Error loading configuration: {}".format(e))
        return {}


# Generate the JSON metrics dynamically based on config
def generate_json_metrics(config):
    data = {}

    # Gather any input fields (like server names) from the config
    input_values = {}
    for key, settings in config.items():
        if settings.get('input', False):
            input_values[key] = settings.get('value')
    # Dynamically add other metrics based on config
    metric_functions = {
        #'app_status': get_app_status,
        'druid_status_health': check_druid_health,
        'test_logic_scala': test_logic_scala,
        'port_80_status': lambda: check_port_status(80),
        'port_8080_status': lambda: check_port_status(8080),
        'rsync_jsons_last_update': lambda: file_age('/var/www/html/load3.srv-analytics.info/srv/crons/input/rsync_monitor.txt'),
        'iptables_line_count': count_iptables_rows,
        'iptables_content_status': check_iptables_content,
        'td_agent_port_status': lambda: check_port_status(24224),
        'geo_ip_last_update': lambda: file_age('/usr/local/share/GeoIP/GeoIP2-City.mmdb'),
        'udger_last_update': lambda: file_age('/usr/local/share/udger/udgerdb_v3.dat'),
        'app_last_update': lambda: file_age("/usr/share/scala/{}/lib/{}".format(folder_name, file_name)),
        'dao_log_last_update': lambda: file_age("/usr/share/scala/{}/lib/{}".format(folder_name, file_name)),
        'counters_log_last_update': lambda: file_age("/usr/share/scala/{}/log/counters.dat".format(folder_name)),
        'pm_status': lambda: check_port_status(9898),
        'aerospike_port_status': lambda: check_port_status(3000),
        'aerospike_service_status': lambda: check_service_status('aerospike'),
        'sentinel_service_status': lambda: check_service_status('sentinelone'),
        'td-agent_service_status': lambda: check_service_status('td-agent'),
        'ssh_service_status': lambda: check_service_status('ssh'),
        'nginx_service_status': lambda: check_service_status('nginx'),
}

    for key, settings in config.items():
        # Only collect if the key has a corresponding function
        if key in metric_functions:
            # Get the metric value from the function
            value = metric_functions[key]()

            # If the key is not marked as 'input', include it in the output
            if not settings.get('input', False):
                data[key] = value

    return data


if __name__ == "__main__":

    config = load_configuration('/opt/monitor_python/conf.json')
    # Generate the metrics based on the config
    data = generate_json_metrics(config)

    # Print the JSON data for Telegraf
    print(json.dumps(data))

    # Write the output to status.json
    try:
        with open('/opt/monitor_python/status.json', 'w') as json_file:
            json.dump(data, json_file, indent=4)
    except Exception as file_error:
        log_error("Error writing JSON to file: {}".format(file_error))
