import os
import subprocess
import logging

# Use a basic logger until the main app logger is configured
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gpu-utils")

def limit_gpu_cores():
    """
    Limits the number of GPU Compute Units (CUs) to N-1.
    Uses HSA_CU_MASK environment variable for ROCm.
    This helps prevent the GPU from being completely saturated,
    keeping the host OS/Window Manager responsive.
    """
    try:
        # 1. Detect CU count using rocminfo
        # Try common paths for rocminfo
        rocminfo_path = "/opt/rocm/bin/rocminfo"
        if not os.path.exists(rocminfo_path):
            rocminfo_path = "rocminfo"

        result = subprocess.run([rocminfo_path], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.warning("rocminfo failed or not found, cannot determine CU count.")
            return

        # 2. Parse for the GPU CU count
        # We look for a node that is a GPU (contains 'gfx') and get its Compute Unit count
        cu_count = None
        current_node_is_gpu = False
        
        # rocminfo output is structured by nodes
        for line in result.stdout.splitlines():
            line = line.strip()
            if "Name:" in line and "gfx" in line:
                current_node_is_gpu = True
            
            # Reset if we hit another node name that isn't a GPU
            elif "Name:" in line and "gfx" not in line and "CPU" in line:
                current_node_is_gpu = False

            if "Compute Unit:" in line and current_node_is_gpu:
                try:
                    # Line looks like: "Compute Unit: 40"
                    val = line.split(":")[1].strip()
                    cu_count = int(val)
                    break # Found the main GPU CU count
                except (ValueError, IndexError):
                    continue
        
        # Fallback: if no gfx node found, just take the first Compute Unit line
        if cu_count is None:
            for line in result.stdout.splitlines():
                if "Compute Unit:" in line:
                    try:
                        cu_count = int(line.split(":")[1].strip())
                        if cu_count > 1: break 
                    except (ValueError, IndexError):
                        continue

        # 3. Apply the mask (target N-1, but max 24 for stability on APUs)
        if cu_count and cu_count > 1:
            limit = min(cu_count - 1, 24)
            # HSA_CU_MASK is a bitmask of CUs to enable.
            # We set 'limit' bits to 1.
            mask_val = (1 << limit) - 1
            mask_hex = hex(mask_val)
            
            # Set environment variable
            os.environ["HSA_CU_MASK"] = mask_hex
            
            logger.info("=" * 60)
            logger.info(f"GPU RESOURCE LIMITER: Detected {cu_count} CUs.")
            logger.info(f"Limiting to {limit} CUs to ensure host stability.")
            logger.info(f"Setting HSA_CU_MASK={mask_hex}")
            logger.info("=" * 60)
        else:
            logger.warning(f"Could not determine valid GPU CU count (found: {cu_count}). Skipping limit.")

    except Exception as e:
        logger.error(f"Error during GPU core limiting: {e}")

if __name__ == "__main__":
    limit_gpu_cores()
    print(f"Final HSA_CU_MASK: {os.environ.get('HSA_CU_MASK', 'Not Set')}")
