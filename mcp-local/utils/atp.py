import json
import subprocess
import os

def extract_run_id(output: str) -> str:
    try:
        data = json.loads(output.split("\n")[1])
        return data.get("data", {}).get("run_id", {})
    except Exception:
        return ""

def run_command(command: list, cwd: str, parse_output=None) -> tuple:
    """
    Run a shell command as a child process and wait for it to finish.
    Optionally parse the output using a provided function.
    Returns (returncode, parsed_output or stdout).
    """
    try:
        #print(command)
        result = subprocess.run(command, cwd=cwd, timeout=60*30, capture_output=True, text=True)
    except subprocess.TimeoutExpired as e:
        print(f"Command timed out: {e}")
        return -1, None
    output = result.stdout
    
    if parse_output:
        output = parse_output(output)
    return result.returncode, output

def read_file_contents(file_path: str) -> str:
    """Read the contents of a file and return as a string."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def prepare_target(remote_ip_addr: str, remote_usr: str, ssh_key_path: str, atperf_dir:str) -> dict:
    """Prepare the target machine for running workloads. 
        Returns the target ID."""
    
    #Check if target already exists
    list_command = ["./atperf", "target", "list", "--json"]
    status, list_output = run_command(list_command, cwd=atperf_dir)
    if status == 0 and list_output:
        try:
            lines = list_output.strip().split("\n")
            json_line = lines[1] if len(lines) > 1 else lines[0]
            data = json.loads(json_line)
            targets = data.get("data", {})
            for target_id, target_info in targets.items():
                value = target_info.get("value", {})
                jumps = value.get("jumps", [])
                if not jumps:
                    continue
                jump = jumps[0]
                t_host = jump.get("host")
                t_user = jump.get("username")
                t_key = jump.get("private_key_filename")
                if t_host == remote_ip_addr and t_user == remote_usr and t_key == ssh_key_path:
                    #print(f"Target already exists: {target_id}")
                    return {
                        "target_id": target_id
                    }
        except Exception as e:
            print(f"Failed to parse target list output: {e}")
    
    generated_name = f"{remote_usr}_{remote_ip_addr.replace('.', '_')}"
    # Add the target if it doesn't exist
    if remote_ip_addr == "172.17.0.1" or "localhost":
        add_command = [
            "./atperf", "target", "add",
            f"{remote_usr}@172.17.0.1:22:{ssh_key_path}",
            "--name", generated_name, "--host-key-policy=ignore"
        ]
    else:
        add_command = [
            "./atperf", "target", "add",
            f"{remote_usr}@{remote_ip_addr}:22:{ssh_key_path}",
            "--name", generated_name
        ]
    add_status, add_output = run_command(add_command, cwd=atperf_dir)
    #if add_status != 0:
        #pass
        #print(f"Warning: Failed to add target (may already exist): {add_output}")

    command = [
        "./atperf",
        "target", "prepare",
        "--target", f"{generated_name}"
    ]
    status, target_id = run_command(command, cwd=atperf_dir)
    if status != 0 or not target_id:
        return {
            "error": "Failed to prepare target. Check the connection details and make sure you have the correct username and ip address. Sometimes when you mean to connect to localhost, you are running from a docker container so the ip address needs to be 172.17.0.1",
            "details": target_id
        }
    return {
        "target_id": generated_name
    }

def run_workload(cmd:str, target: str, recipe:str, atperf_dir:str) -> dict:
    """Run a sample workload on the target machine. Some example queries: 
        - 'Help my analyze my code's performance'.
        - 'Find the CPU hotspots in my application'.
        Returns the run ID of the workload execution."""
    command = [
        "./atperf",
        "recipe", "run", recipe,
        f"--workload={cmd}",
        "--json",
        f"--target={target}"
    ]
    status, run_id = run_command(command, cwd=atperf_dir, parse_output=extract_run_id)
    if not run_id:
        return {
            "error": "Failed to run workload on target machine.",
            "details": run_id
        }
    return {"run_id": run_id}

def get_results(run_id: dict, table: str, atperf_dir:str) -> str:
    """Get results from the target machine after running a workload. 
        Returns a csv of the run results, which are sampling data 
        for the different function calls."""
    
    # Startup the local db for querying results
    render_cmd = ["./atperf", "run", "render", run_id['value']]
    #print(render_cmd)
    render_proc = subprocess.run(render_cmd, cwd=atperf_dir, timeout=60*5, capture_output=True, text=True)
    #print(render_proc.stdout)
    if render_proc.returncode != 0:
        return f"atperf render failed. {render_proc.stderr}"

    # Parse session id and table from JSON output
    try:
        render_json = json.loads(render_proc.stdout)
        session_id = render_json.get("data").get("invocation").get("session_id")
        if not session_id:
            return "Failed to get session ID from render output."
    except Exception as e:
        raise RuntimeError(f"Failed to parse render output: {e}")

    # Query the DB for csv results to send to Agent
    query_cmd = ["./atperf", "render", "query", session_id, f"select * from {table}"]
    query_proc = subprocess.run(query_cmd, cwd=atperf_dir, capture_output=True, text=True)
    if query_proc.returncode != 0:
        return f"atperf render query failed. {query_proc.stderr}"

    return query_proc.stdout