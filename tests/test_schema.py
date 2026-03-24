import json
import os
import sys

# Get this package's directory (the parent of the tests folder)
package_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, package_dir)

from schema_to_node import schema_to_comfyui_input_types, get_return_type

# Get the directory where this script is located (tests folder)
script_dir = os.path.dirname(os.path.abspath(__file__))

# Get the schemas directory relative to the tests folder
schemas_dir = os.path.join(script_dir, "..", "schemas")
schemas_dir = os.path.normpath(schemas_dir)

schema_files = [f for f in os.listdir(schemas_dir) if f.endswith(".json")]

# Print table header
print(f"{'Schema Name':<50} {'Inputs':<25} {'Parameters':<25} {'Outputs':<15}")
print("=" * 120)

for schema_file in sorted(schema_files):
    schema_path = os.path.join(schemas_dir, schema_file)
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    
    # Get input types
    result = schema_to_comfyui_input_types(schema)
    
    # Get return types
    return_types = get_return_type(schema)
    
    # Get schema name (either from endpointId or from filename)
    endpoint_id = schema.get("info", {}).get("x-fal-metadata", {}).get("endpointId")
    if not endpoint_id:
        # Use filename without .json extension
        endpoint_id = schema_file.replace(".json", "")
    
    # Separate inputs (IMAGE type) from parameters (all other types)
    # Inputs are what users connect from other nodes (IMAGE type)
    # Parameters are dialog box settings (STRING, INT, FLOAT, BOOLEAN, enums)
    
    all_required = result.get("required", {})
    all_optional = result.get("optional", {})
    
    # Combine required and optional inputs
    all_inputs = {}
    all_inputs.update(all_required)
    all_inputs.update(all_optional)
    
    # Separate into Inputs (IMAGE) and Parameters (everything else)
    inputs_list = [(name, inp) for name, inp in all_inputs.items() if inp[0] == "IMAGE"]
    parameters_list = [(name, inp) for name, inp in all_inputs.items() if inp[0] != "IMAGE"]
    
    # Format outputs - just the type, not the name
    if return_types:
        output_str = ", ".join([v for v in return_types.values()])
    else:
        output_str = "None"
    
    # Determine max rows needed
    max_rows = max(len(inputs_list), len(parameters_list), 1)
    
    for i in range(max_rows):
        input_name = ""
        input_type = ""
        param_name = ""
        param_type = ""
        
        if i < len(inputs_list):
            input_name = inputs_list[i][0]
            input_type = inputs_list[i][1][0]
        
        if i < len(parameters_list):
            param_name = parameters_list[i][0]
            param_type = parameters_list[i][1][0]
            # Handle enum case where param_type is a list
            if isinstance(param_type, list):
                param_type = str(param_type)
        
        if i == 0:
            print(f"{endpoint_id:<50} {input_name:<25} {param_name:<25} {output_str:<15}")
        else:
            print(f"{'':<50} {input_name:<25} {param_name:<25} {'':<15}")
