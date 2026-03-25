DEFAULT_STEP = 0.01
DEFAULT_ROUND = 0.001

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".mpg", ".mpeg")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".mpga", ".m4a")

TYPE_MAPPING = {
    "string": "STRING",
    "integer": "INT",
    "number": "FLOAT",
    "boolean": "BOOLEAN",
}


def convert_to_comfyui_input_type(
    input_name, openapi_type, openapi_format=None, default_example_input=None, items_type=None, items_format=None
):
    if openapi_type == "string":
        # Check for URI format or name containing image/audio/video
        if openapi_format == "uri":
            if (
                default_example_input
                and isinstance(default_example_input, dict)
                and input_name in default_example_input
            ):
                if is_type(default_example_input[input_name], IMAGE_EXTENSIONS):
                    return "IMAGE"
                elif is_type(default_example_input[input_name], VIDEO_EXTENSIONS):
                    return "VIDEO"
                elif is_type(default_example_input[input_name], AUDIO_EXTENSIONS):
                    return "AUDIO"
            elif any(x in input_name.lower() for x in ["image", "mask"]):
                return "IMAGE"
            elif "audio" in input_name.lower():
                return "AUDIO"
            elif "video" in input_name.lower():
                return "VIDEO"
            else:
                return "STRING"
        elif any(x in input_name.lower() for x in ["image", "mask"]):
            return "IMAGE"
        elif "audio" in input_name.lower():
            return "AUDIO"
        elif "video" in input_name.lower():
            return "VIDEO"
        else:
            return "STRING"

    # Handle array types - check if items are uri strings (images/audio/video)
    if openapi_type == "array" and items_type == "string":
        # Check items_format or use input name to determine type
        if items_format == "uri":
            if any(x in input_name.lower() for x in ["image", "mask"]):
                return "IMAGE"
            elif "audio" in input_name.lower():
                return "AUDIO"
            elif "video" in input_name.lower():
                return "VIDEO"
        # Also check if input name indicates image/audio/video array even without format
        if any(x in input_name.lower() for x in ["image", "mask"]):
            return "IMAGE"
        elif "audio" in input_name.lower():
            return "AUDIO"
        elif "video" in input_name.lower():
            return "VIDEO"

    return TYPE_MAPPING.get(openapi_type, "STRING")


def name_and_version(schema):
    # For Fal AI, use the endpointId from x-fal-metadata
    endpoint_id = schema.get("info", {}).get("x-fal-metadata", {}).get("endpointId")
    if not endpoint_id:
        # Fallback to owner/name format
        author = schema["owner"]
        name = schema["name"]
        endpoint_id = f"{author}/{name}"
    
    version = "latest"
    
    fal_model = endpoint_id
    node_name = f"Fal AI {endpoint_id}"
    return fal_model, node_name


def resolve_schema(prop_data, openapi_schema):
    if "$ref" in prop_data:
        ref_path = prop_data["$ref"].split("/")
        current = openapi_schema
        for path in ref_path[1:]:  # Skip the first '#' element
            if path not in current:
                return prop_data  # Return original if path is invalid
            current = current[path]
        return current
    return prop_data


def schema_to_comfyui_input_types(schema):
    # Get schemas from components
    openapi_schema = schema.get("components", {}).get("schemas", {})
    
    # Determine input schema based on structure
    # For Fal AI: look for *Input schema (e.g., Flux2Klein9bEditInput)
    input_schema = None
    
    if "Input" in openapi_schema:
        input_schema = openapi_schema["Input"]
    else:
        # Fal AI format: find schema ending with 'Input'
        for key in openapi_schema:
            if key.endswith("Input"):
                input_schema = openapi_schema[key]
                break
        if input_schema is None:
            # Try first schema if no Input found
            input_schema = list(openapi_schema.values())[0] if openapi_schema else {}
    
    if not isinstance(input_schema, dict) or "properties" not in input_schema:
        return {"required": {}, "optional": {}}
    
    input_types = {"required": {}, "optional": {}}
    default_example_input = get_default_example_input(schema)

    required_props = input_schema.get("required", [])

    for prop_name, prop_data in input_schema["properties"].items():
        prop_data = resolve_schema(prop_data, openapi_schema)
        default_value = prop_data.get("default", None)

        if "allOf" in prop_data:
            prop_data = resolve_schema(prop_data["allOf"][0], openapi_schema)

        # Extract items info for array types
        items_type = None
        items_format = None
        if prop_data.get("type") == "array" and "items" in prop_data:
            items_type = prop_data["items"].get("type")
            items_format = prop_data["items"].get("format")

        if "enum" in prop_data:
            input_type = prop_data["enum"]
        elif "type" in prop_data:
            input_type = convert_to_comfyui_input_type(
                prop_name,
                prop_data["type"],
                prop_data.get("format"),
                default_example_input,
                items_type,
                items_format,
            )
        else:
            input_type = "STRING"

        input_config = {"default": default_value} if default_value is not None else {}

        if "minimum" in prop_data:
            input_config["min"] = prop_data["minimum"]
        if "maximum" in prop_data:
            input_config["max"] = prop_data["maximum"]
        if input_type == "FLOAT":
            input_config["step"] = DEFAULT_STEP
            input_config["round"] = DEFAULT_ROUND

        if "prompt" in prop_name and prop_data.get("type") == "string":
            input_config["multiline"] = True

            # Meta prompt_template needs `{prompt}` to be sent through
            # dynamicPrompts would strip it out
            if "template" not in prop_name:
                input_config["dynamicPrompts"] = True

        if prop_name in required_props:
            input_types["required"][prop_name] = (input_type, input_config)
        else:
            input_types["optional"][prop_name] = (input_type, input_config)

    input_types["optional"]["force_rerun"] = ("BOOLEAN", {"default": False})
    input_types["optional"]["debug"] = ("BOOLEAN", {"default": False})

    # Handle array inputs with max item count - split into individual optional inputs
    input_types = handle_array_inputs_as_multiple(input_types, input_schema)

    return order_inputs(input_types, input_schema)


def handle_array_inputs_as_multiple(input_types, input_schema):
    """
    Handle array inputs that should be converted to multiple optional inputs.
    
    For example, if there's an 'image_urls' array input with num_images.maximum = 4,
    convert it to 4 optional IMAGE inputs: image_url_1, image_url_2, image_url_3, image_url_4.
    """
    if not input_schema or "properties" not in input_schema:
        return input_types
    
    properties = input_schema["properties"]
    
    # Find properties with max item count (like num_images)
    max_items = {}
    for prop_name, prop_data in properties.items():
        if "maximum" in prop_data:
            max_items[prop_name] = prop_data["maximum"]
    
    if not max_items:
        return input_types
    
    # Find array inputs that might need to be split
    for prop_name, prop_data in properties.items():
        if prop_data.get("type") == "array" and "items" in prop_data:
            items = prop_data["items"]
            
            # Check if it's a string array (like image_urls)
            if items.get("type") == "string":
                # Look for a corresponding num_images property
                # Common patterns: num_images, max_images, etc.
                for max_prop, max_val in max_items.items():
                    # Check if max_prop relates to prop_name (e.g., num_images relates to image_urls)
                    # Common patterns:
                    # - num_images <-> image_urls, images
                    # - max_count <-> items
                    # Check for keyword-based matching
                    max_keywords = ["num", "max", "count"]
                    prop_keywords = ["image", "url", "file", "item"]
                    
                    max_base = max_prop.lower().replace("_", "")
                    prop_base = prop_name.lower().replace("_", "")
                    
                    is_related = False
                    for mk in max_keywords:
                        if mk in max_base:
                            for pk in prop_keywords:
                                if pk in prop_base:
                                    is_related = True
                                    break
                        if is_related:
                            break
                    
                    # Also check direct substring matching as fallback
                    if not is_related:
                        is_related = (max_base in prop_base or prop_base in max_base)
                    
                    if is_related:
                        
                        # Convert to multiple optional IMAGE inputs
                        # Remove from required/optional
                        if prop_name in input_types["required"]:
                            del input_types["required"][prop_name]
                        if prop_name in input_types["optional"]:
                            del input_types["optional"][prop_name]
                        
                        # Add optional IMAGE inputs for each item
                        base_name = prop_name.replace("urls", "url").replace("_url", "")
                        for i in range(1, int(max_val) + 1):
                            input_name = f"{base_name}_{i}"
                            input_types["optional"][input_name] = ("IMAGE", {})
                        
                        break
    
    return input_types


def order_inputs(input_types, input_schema):
    ordered_input_types = {"required": {}, "optional": {}}
    properties = input_schema.get("properties", {})
    sorted_properties = sorted(
        properties.items(),
        key=lambda x: x[1].get("x-order", float("inf")),
    )

    for prop_name, _ in sorted_properties:
        if prop_name in input_types["required"]:
            ordered_input_types["required"][prop_name] = input_types["required"][
                prop_name
            ]
        elif prop_name in input_types["optional"]:
            ordered_input_types["optional"][prop_name] = input_types["optional"][
                prop_name
            ]

    # Also add any new inputs created by handle_array_inputs_as_multiple
    # (these have numeric suffixes like image_1, image_2, etc.)
    for prop_name in input_types["optional"]:
        if prop_name not in ordered_input_types["optional"]:
            ordered_input_types["optional"][prop_name] = input_types["optional"][
                prop_name
            ]

    ordered_input_types["optional"]["force_rerun"] = input_types["optional"][
        "force_rerun"
    ]

    return ordered_input_types


def inputs_that_need_arrays(schema):
    # Get schemas from components
    openapi_schema = schema.get("components", {}).get("schemas", {})
    
    # Determine input schema based on structure
    # For Fal AI: look for *Input schema (e.g., Flux2Klein9bEditInput)
    if "Input" in openapi_schema:
        input_schema = openapi_schema["Input"]
    else:
        # Fal AI format: find schema ending with 'Input'
        input_schema = None
        for key in openapi_schema:
            if key.endswith("Input"):
                input_schema = openapi_schema[key]
                break
        if input_schema is None:
            input_schema = list(openapi_schema.values())[0] if openapi_schema else {}
    
    if not isinstance(input_schema, dict):
        return []
    
    array_inputs = []
    for prop_name, prop_data in input_schema.get("properties", {}).items():
        prop_data = resolve_schema(prop_data, openapi_schema)
        if "allOf" in prop_data:
            prop_data = resolve_schema(prop_data["allOf"][0], openapi_schema)
        if prop_data.get("type") == "array":
            array_inputs.append(prop_name)

    return array_inputs


def is_type(default_example_output, extensions):
    if isinstance(
        default_example_output, str
    ) and default_example_output.lower().endswith(extensions):
        return True
    elif (
        isinstance(default_example_output, list)
        and default_example_output
        and isinstance(default_example_output[0], str)
        and default_example_output[0].lower().endswith(extensions)
    ):
        return True
    return False


def get_default_example(schema):
    default_example = schema.get("default_example")
    return default_example if default_example else None


def get_default_example_input(schema):
    default_example = get_default_example(schema)
    return default_example.get("input") if default_example else None


def get_default_example_output(schema):
    default_example = get_default_example(schema)
    return default_example.get("output") if default_example else None


def get_return_type(schema):
    # Get schemas from components
    openapi_schema = schema.get("components", {}).get("schemas", {})
    
    # Use full schema for resolving $ref paths that include components/schemas
    full_schema = schema
    
    # Determine output schema based on structure
    # For Fal AI: look for *Output schema (e.g., Flux2Klein9bEditOutput)
    if "Output" in openapi_schema:
        output_schema = openapi_schema["Output"]
    else:
        # Fal AI format: find schema ending with 'Output'
        output_schema = None
        for key in openapi_schema:
            if key.endswith("Output"):
                output_schema = openapi_schema[key]
                break
        if output_schema is None:
            # Try to find any schema with uri format (image/audio outputs)
            for key, val in openapi_schema.items():
                if isinstance(val, dict) and val.get("format") == "uri":
                    output_schema = val
                    break
            if output_schema is None:
                output_schema = {}
    
    default_example_output = get_default_example_output(schema)

    if output_schema and "$ref" in output_schema:
        output_schema = resolve_schema(output_schema, full_schema)

    if isinstance(output_schema, dict) and output_schema.get("properties"):
        return_types = {}
        for prop_name, prop_data in output_schema["properties"].items():
            # Check for single object with $ref (like image: {$ref: ImageFile})
            # Note: type might be null when $ref is present
            if "$ref" in prop_data:
                ref_schema = resolve_schema(prop_data, full_schema)
                if ref_schema and ref_schema.get("properties"):
                    # Check for url property with uri format
                    url_prop = ref_schema.get("properties", {}).get("url", {})
                    if url_prop.get("format") == "uri":
                        if "image" in prop_name.lower() or "img" in prop_name.lower():
                            return_types[prop_name] = "IMAGE"
                        elif "audio" in prop_name.lower():
                            return_types[prop_name] = "AUDIO"
                        elif "video" in prop_name.lower():
                            return_types[prop_name] = "VIDEO_URI"
                        continue
                    # Check content_type for image indication
                    ct_prop = ref_schema.get("properties", {}).get("content_type", {})
                    if ct_prop and "image" in str(ct_prop).lower():
                        if "image" in prop_name.lower() or "img" in prop_name.lower():
                            return_types[prop_name] = "IMAGE"
                        elif "audio" in prop_name.lower():
                            return_types[prop_name] = "AUDIO"
                        elif "video" in prop_name.lower():
                            return_types[prop_name] = "VIDEO_URI"
                        continue
                    # Check if title indicates image type
                    title = ref_schema.get("title", "").lower() if ref_schema else ""
                    if "image" in prop_name.lower() or "img" in prop_name.lower() or "image" in title:
                        return_types[prop_name] = "IMAGE"
                    elif "audio" in prop_name.lower() or "audio" in title:
                        return_types[prop_name] = "AUDIO"
                    elif "video" in prop_name.lower() or "video" in title:
                        return_types[prop_name] = "VIDEO_URI"
                    else:
                        return_types[prop_name] = "STRING"
                    continue
            
            # Check if this is an array with items that reference another schema (like ImageFile)
            if prop_data.get("type") == "array" and "items" in prop_data:
                items = prop_data["items"]
                # Check if items reference another schema
                if "$ref" in items:
                    ref = items["$ref"]
                    # Resolve the reference to get the actual schema
                    resolved = resolve_schema(items, openapi_schema)
                    # Check the resolved schema for format or content_type
                    if resolved:
                        # Check for format: uri
                        if resolved.get("format") == "uri":
                            if "image" in prop_name.lower():
                                return_types[prop_name] = "IMAGE"
                            elif "audio" in prop_name.lower():
                                return_types[prop_name] = "AUDIO"
                            elif "video" in prop_name.lower():
                                return_types[prop_name] = "VIDEO_URI"
                            continue
                        
                        # Check content_type property in the referenced schema
                        if resolved.get("properties"):
                            ct_prop = resolved.get("properties", {}).get("content_type", {})
                            if ct_prop and "image" in str(ct_prop).lower():
                                if "image" in prop_name.lower() or "img" in prop_name.lower():
                                    return_types[prop_name] = "IMAGE"
                                elif "audio" in prop_name.lower():
                                    return_types[prop_name] = "AUDIO"
                                elif "video" in prop_name.lower():
                                    return_types[prop_name] = "VIDEO_URI"
                                continue
                        
                        # Check title of the referenced schema
                        title = resolved.get("title", "").lower() if resolved else ""
                        if "image" in prop_name.lower() or "img" in prop_name.lower() or "image" in title:
                            return_types[prop_name] = "IMAGE"
                        elif "audio" in prop_name.lower() or "audio" in title:
                            return_types[prop_name] = "AUDIO"
                        elif "video" in prop_name.lower() or "video" in title:
                            return_types[prop_name] = "VIDEO_URI"
                        else:
                            return_types[prop_name] = "STRING"
                    else:
                        return_types[prop_name] = "STRING"
                elif items.get("format") == "uri":
                    if "image" in prop_name.lower():
                        return_types[prop_name] = "IMAGE"
                    elif "audio" in prop_name.lower():
                        return_types[prop_name] = "AUDIO"
                    elif "video" in prop_name.lower():
                        return_types[prop_name] = "VIDEO_URI"
                    else:
                        return_types[prop_name] = "STRING"
                elif items.get("type") == "string":
                    if "image" in prop_name.lower():
                        return_types[prop_name] = "IMAGE"
                    elif "audio" in prop_name.lower():
                        return_types[prop_name] = "AUDIO"
                    elif "video" in prop_name.lower():
                        return_types[prop_name] = "VIDEO_URI"
                    else:
                        return_types[prop_name] = "STRING"
                else:
                    return_types[prop_name] = "STRING"
            elif isinstance(default_example_output, dict):
                prop_value = default_example_output.get(prop_name)

                if is_type(prop_value, IMAGE_EXTENSIONS):
                    return_types[prop_name] = "IMAGE"
                elif is_type(prop_value, AUDIO_EXTENSIONS):
                    return_types[prop_name] = "AUDIO"
                elif is_type(prop_value, VIDEO_EXTENSIONS):
                    return_types[prop_name] = "VIDEO_URI"
                else:
                    return_types[prop_name] = "STRING"
            elif prop_data.get("format") == "uri":
                if "audio" in prop_name.lower():
                    return_types[prop_name] = "AUDIO"
                elif "image" in prop_name.lower():
                    return_types[prop_name] = "IMAGE"
                else:
                    return_types[prop_name] = "STRING"
            elif prop_data.get("type") == "string":
                return_types[prop_name] = "STRING"
            else:
                return_types[prop_name] = "STRING"

        # Filter to only include IMAGE, AUDIO, and VIDEO_URI types
        filtered_return_types = {k: v for k, v in return_types.items() if v in ("IMAGE", "AUDIO", "VIDEO_URI")}
        return filtered_return_types

    if is_type(default_example_output, IMAGE_EXTENSIONS):
        return "IMAGE"
    elif is_type(default_example_output, VIDEO_EXTENSIONS):
        return "VIDEO_URI"
    elif is_type(default_example_output, AUDIO_EXTENSIONS):
        return "AUDIO"

    if output_schema:
        if (
            output_schema.get("type") == "string"
            and output_schema.get("format") == "uri"
        ):
            # Handle single image output
            return "IMAGE"
        elif (
            output_schema.get("type") == "array"
            and output_schema.get("items", {}).get("type") == "string"
            and output_schema.get("items", {}).get("format") == "uri"
        ):
            # Handle multiple image output
            return "IMAGE"

    return "STRING"
