# /// script
# dependencies = [
#   "mcp",
#   "requests",
#   "pydantic"
# ]
# ///
import os
import json
import platform
import subprocess
import socket
from typing import Dict, Any, Optional

# Initialize FastMCP server


def check_model_identity() -> Dict[str, Any]:
    """
    Check the actual model identity based on environment variables and configuration.
    This tool helps AI agents determine which model they are actually running on,
    rather than relying on training data assumptions.

    Returns comprehensive information about the current model configuration.
    """
    identity = {
        "environment_variables": {},
        "detected_model": None,
        "detected_provider": None,
        "api_endpoint": None,
        "evidence": []
    }

    # Check all relevant environment variables
    env_vars_to_check = [
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "MIMO_API_KEY",
        "CLAUDE_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "GOOGLE_API_KEY",
        "AI_MODEL",
        "MODEL_NAME",
        "LLM_PROVIDER"
    ]

    for var in env_vars_to_check:
        value = os.environ.get(var)
        if value:
            # Mask sensitive keys
            if "KEY" in var or "TOKEN" in var:
                masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                identity["environment_variables"][var] = masked
            else:
                identity["environment_variables"][var] = value

    # Analyze base URL to determine provider
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if base_url:
        identity["api_endpoint"] = base_url

        if "xiaomimimo.com" in base_url or "mimo" in base_url.lower():
            identity["detected_provider"] = "Xiaomi MiMo"
            identity["evidence"].append(f"API endpoint contains 'mimo': {base_url}")
        elif "anthropic.com" in base_url:
            identity["detected_provider"] = "Anthropic"
            identity["evidence"].append(f"API endpoint is Anthropic: {base_url}")
        elif "openai.com" in base_url:
            identity["detected_provider"] = "OpenAI"
            identity["evidence"].append(f"API endpoint is OpenAI: {base_url}")
        else:
            identity["detected_provider"] = f"Unknown ({base_url})"
            identity["evidence"].append(f"API endpoint: {base_url}")

    # Check model name
    model_name = os.environ.get("ANTHROPIC_MODEL", "")
    if model_name:
        identity["detected_model"] = model_name

        if "mimo" in model_name.lower():
            identity["evidence"].append(f"Model name contains 'mimo': {model_name}")
        elif "claude" in model_name.lower():
            identity["evidence"].append(f"Model name contains 'claude': {model_name}")
        elif "gpt" in model_name.lower():
            identity["evidence"].append(f"Model name contains 'gpt': {model_name}")

    # Check for MiMo-specific keys
    if os.environ.get("MIMO_API_KEY"):
        identity["evidence"].append("MIMO_API_KEY is set - indicates Xiaomi MiMo provider")

    # Summary
    if identity["detected_provider"] and identity["detected_model"]:
        identity["summary"] = f"Running {identity['detected_model']} via {identity['detected_provider']}"
    elif identity["detected_provider"]:
        identity["summary"] = f"Provider: {identity['detected_provider']} (model name not detected)"
    elif identity["detected_model"]:
        identity["summary"] = f"Model: {identity['detected_model']} (provider not detected)"
    else:
        identity["summary"] = "Could not determine model identity from environment"

    return identity


def check_runtime_environment() -> Dict[str, Any]:
    """
    Check the runtime environment to gather additional evidence about the model.
    This includes system info, process details, and other contextual clues.
    """
    env_info = {
        "system": {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
        },
        "environment": {
            "shell": os.environ.get("SHELL", "Not set"),
            "user": os.environ.get("USER", os.environ.get("USERNAME", "Unknown")),
            "home": os.environ.get("HOME", os.environ.get("USERPROFILE", "Unknown")),
            "pwd": os.environ.get("PWD", "Unknown"),
        },
        "claude_code_specific": {
            "session_id": os.environ.get("CLAUDE_CODE_SESSION_ID", "Not set"),
            "effort_level": os.environ.get("CLAUDE_EFFORT", "Not set"),
            "disable_nonessential_traffic": os.environ.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "Not set"),
            "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT", "Not set"),
            "execpath": os.environ.get("CLAUDE_CODE_EXECPATH", "Not set"),
        },
        "evidence": []
    }

    # Check for Claude Code specific indicators
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        env_info["evidence"].append("Running inside Claude Code session")

    if os.environ.get("CLAUDE_CODE_EXECPATH"):
        env_info["evidence"].append(f"Claude Code executable: {os.environ.get('CLAUDE_CODE_EXECPATH')}")

    # Check for containerization
    if os.path.exists("/.dockerenv"):
        env_info["evidence"].append("Running inside Docker container")

    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        env_info["evidence"].append("Running in Kubernetes cluster")

    return env_info


def check_api_connectivity() -> Dict[str, Any]:
    """
    Test connectivity to the configured API endpoint.
    This can help verify which API service is actually being used.
    """
    import requests

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not base_url:
        return {"error": "No ANTHROPIC_BASE_URL configured"}

    try:
        # Try to hit a common endpoint
        response = requests.get(f"{base_url}/models", timeout=5, headers={
            "Authorization": f"Bearer {os.environ.get('ANTHROPIC_AUTH_TOKEN', '')}"
        })
        return {
            "endpoint": base_url,
            "status_code": response.status_code,
            "response_preview": response.text[:500] if response.text else "No response body",
            "headers": dict(response.headers)
        }
    except Exception as e:
        return {
            "endpoint": base_url,
            "error": str(e)
        }


def get_model_config() -> Dict[str, Any]:
    """
    Get the full model configuration (non-sensitive parts).
    Useful for debugging and understanding the current setup.
    """
    config = {
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", "Not set"),
        "model": os.environ.get("ANTHROPIC_MODEL", "Not set"),
        "has_mimo_key": bool(os.environ.get("MIMO_API_KEY")),
        "has_anthropic_key": bool(os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "session_id": os.environ.get("CLAUDE_CODE_SESSION_ID", "Not set"),
        "effort_level": os.environ.get("CLAUDE_EFFORT", "Not set"),
        "subagent_model": os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL", "Not set"),
    }
    return config


def analyze_model_characteristics() -> Dict[str, Any]:
    """
    Analyze model characteristics based on available clues.
    This tool synthesizes information from multiple sources to make an informed guess
    about the actual model being used.
    """
    characteristics = {
        "likely_model_family": None,
        "confidence_score": 0,
        "reasoning": [],
        "counter_evidence": []
    }

    # Gather evidence
    model_name = os.environ.get("ANTHROPIC_MODEL", "").lower()
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").lower()
    has_mimo_key = bool(os.environ.get("MIMO_API_KEY"))
    has_anthropic_key = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    # Check for MiMo indicators
    mimo_score = 0
    if "mimo" in model_name:
        mimo_score += 40
        characteristics["reasoning"].append(f"Model name contains 'mimo': {model_name}")
    if "xiaomimimo" in base_url or "mimo" in base_url:
        mimo_score += 30
        characteristics["reasoning"].append(f"API endpoint suggests MiMo: {base_url}")
    if has_mimo_key:
        mimo_score += 20
        characteristics["reasoning"].append("MIMO_API_KEY is present")

    # Check for Claude indicators
    claude_score = 0
    if "claude" in model_name:
        claude_score += 40
        characteristics["reasoning"].append(f"Model name contains 'claude': {model_name}")
    if "anthropic" in base_url:
        claude_score += 30
        characteristics["reasoning"].append(f"API endpoint is Anthropic: {base_url}")
    if has_anthropic_key and not has_mimo_key:
        claude_score += 20
        characteristics["reasoning"].append("Only ANTHROPIC_AUTH_TOKEN present (no MIMO key)")

    # Check for OpenAI indicators
    openai_score = 0
    if "gpt" in model_name:
        openai_score += 40
        characteristics["reasoning"].append(f"Model name contains 'gpt': {model_name}")
    if "openai" in base_url:
        openai_score += 30
        characteristics["reasoning"].append(f"API endpoint is OpenAI: {base_url}")

    # Determine most likely model
    scores = {
        "MiMo": mimo_score,
        "Claude": claude_score,
        "OpenAI": openai_score
    }

    max_score = max(scores.values())
    if max_score > 0:
        for model, score in scores.items():
            if score == max_score:
                characteristics["likely_model_family"] = model
                characteristics["confidence_score"] = min(score, 100)
                break

    # Add counter-evidence
    if mimo_score > 0 and claude_score > 0:
        characteristics["counter_evidence"].append("Mixed signals: both MiMo and Claude indicators present")
    if mimo_score > 0 and openai_score > 0:
        characteristics["counter_evidence"].append("Mixed signals: both MiMo and OpenAI indicators present")

    return characteristics


def verify_api_endpoint() -> Dict[str, Any]:
    """
    Actually call the configured API endpoint to verify it's real.
    This is the most reliable way to confirm which service is being used.
    """
    import requests

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    if not base_url:
        return {"error": "No ANTHROPIC_BASE_URL configured"}

    result = {
        "endpoint": base_url,
        "tests": []
    }

    # Test 1: Basic connectivity
    try:
        response = requests.get(base_url, timeout=5)
        result["tests"].append({
            "test": "basic_connectivity",
            "success": True,
            "status_code": response.status_code,
            "headers": dict(response.headers)
        })
    except Exception as e:
        result["tests"].append({
            "test": "basic_connectivity",
            "success": False,
            "error": str(e)
        })

    # Test 2: Models endpoint (if available)
    try:
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        response = requests.get(f"{base_url}/models", timeout=5, headers=headers)
        result["tests"].append({
            "test": "models_endpoint",
            "success": True,
            "status_code": response.status_code,
            "response_preview": response.text[:500] if response.text else "No response"
        })
    except Exception as e:
        result["tests"].append({
            "test": "models_endpoint",
            "success": False,
            "error": str(e)
        })

    # Test 3: Check DNS resolution
    try:
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        hostname = parsed.hostname
        ip = socket.gethostbyname(hostname)
        result["tests"].append({
            "test": "dns_resolution",
            "success": True,
            "hostname": hostname,
            "resolved_ip": ip
        })
    except Exception as e:
        result["tests"].append({
            "test": "dns_resolution",
            "success": False,
            "error": str(e)
        })

    return result


def check_network_connections() -> Dict[str, Any]:
    """
    Check active network connections to see which servers are actually being connected to.
    This can reveal the true API endpoint even if environment variables are misleading.
    """
    connections = []

    try:
        # Use netstat to check connections (Windows/Linux compatible)
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-an"],
                capture_output=True,
                text=True,
                timeout=5
            )
        else:
            result = subprocess.run(
                ["netstat", "-an"],
                capture_output=True,
                text=True,
                timeout=5
            )

        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines:
                if 'ESTABLISHED' in line:
                    connections.append(line.strip())
    except Exception as e:
        return {"error": f"Failed to check connections: {e}"}

    # Filter for likely API connections
    api_connections = []
    for conn in connections:
        if any(keyword in conn.lower() for keyword in ['anthropic', 'openai', 'mimo', 'api']):
            api_connections.append(conn)

    return {
        "total_established_connections": len(connections),
        "api_related_connections": api_connections[:10],  # Limit to first 10
        "all_connections_sample": connections[:20]  # Sample of all connections
    }


def check_process_info() -> Dict[str, Any]:
    """
    Check running processes for Claude Code and related services.
    This can reveal how the system is actually configured.
    """
    processes = []

    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq claude.exe"],
                capture_output=True,
                text=True,
                timeout=5
            )
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5
            )

        if result.returncode == 0:
            processes = result.stdout.split('\n')[:20]  # First 20 lines
    except Exception as e:
        return {"error": f"Failed to check processes: {e}"}

    return {
        "platform": platform.system(),
        "processes": processes
    }


def comprehensive_identity_check() -> Dict[str, Any]:
    """
    Perform a comprehensive identity check using all available methods.
    This is the most thorough way to determine the actual model identity.
    """
    results = {
        "environment_check": check_model_identity(),
        "runtime_check": check_runtime_environment(),
        "characteristics_check": analyze_model_characteristics(),
        "api_verification": verify_api_endpoint(),
        "network_check": check_network_connections(),
        "process_check": check_process_info(),
        "final_verdict": None,
        "confidence_score": 0,
        "evidence_summary": []
    }

    # Analyze all evidence
    evidence_points = []

    # From environment check
    env_check = results["environment_check"]
    if env_check.get("detected_provider"):
        evidence_points.append(f"Provider: {env_check['detected_provider']}")
    if env_check.get("detected_model"):
        evidence_points.append(f"Model: {env_check['detected_model']}")

    # From API verification
    api_check = results["api_verification"]
    for test in api_check.get("tests", []):
        if test.get("success"):
            evidence_points.append(f"API test passed: {test['test']}")

    # From network check
    net_check = results["network_check"]
    if net_check.get("api_related_connections"):
        evidence_points.append(f"Found {len(net_check['api_related_connections'])} API connections")

    # Calculate confidence
    confidence = min(len(evidence_points) * 15, 100)  # 15 points per evidence, max 100

    # Determine verdict
    provider = env_check.get("detected_provider", "Unknown")
    model = env_check.get("detected_model", "Unknown")

    if provider != "Unknown" and model != "Unknown":
        verdict = f"Running {model} via {provider}"
    elif provider != "Unknown":
        verdict = f"Provider: {provider} (model unclear)"
    elif model != "Unknown":
        verdict = f"Model: {model} (provider unclear)"
    else:
        verdict = "Unable to determine identity"

    results["final_verdict"] = verdict
    results["confidence_score"] = confidence
    results["evidence_summary"] = evidence_points

    return results

