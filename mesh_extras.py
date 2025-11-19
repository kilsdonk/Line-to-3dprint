import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET
import numpy as np
import json
from pathlib import Path

# =====================================
# MESH_EXTRAS.PY FOR BAMBUSTUDIO H2D COMPATIBILITY
# CONVERTS ORCASLICER FORMAT TO BAMBUSTUDIO FORMAT
# =====================================

def add_metadata_to_3mf(input_3mf_path, output_3mf_path, meshes_metadata):
    """
    Add BambuStudio metadata to a 3MF file
    
    Args:
        input_3mf_path: Path to the input 3MF file
        output_3mf_path: Path to save the output 3MF file
        meshes_metadata: List of dicts with mesh metadata (name, filament_id, wall_loops, bottom_shell_layers)
    
    Returns:
        Path to the processed 3MF file
    """
    # Create the output file
    with zipfile.ZipFile(output_3mf_path, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        # Process and copy the 3dmodel.model file
        with zipfile.ZipFile(input_3mf_path, 'r') as in_zip:
            # Copy standard content files that don't need modification
            for item in in_zip.infolist():
                if item.filename in ['[Content_Types].xml', '_rels/.rels']:
                    out_zip.writestr(item, in_zip.read(item))
            
            # Process the 3D model file
            if '3D/3dmodel.model' in [item.filename for item in in_zip.infolist()]:
                model_content = in_zip.read('3D/3dmodel.model')
                modified_model = modify_3mf_model(model_content, meshes_metadata)
                out_zip.writestr('3D/3dmodel.model', modified_model)
        
        # Add BambuStudio metadata files
        add_bambustudio_metadata(out_zip, meshes_metadata)
    
    return output_3mf_path

def modify_3mf_model(model_content, meshes_metadata):
    """
    Completely restructure the 3D model XML to match BambuStudio format
    
    Args:
        model_content: XML content as bytes
        meshes_metadata: List of dicts with mesh metadata
    
    Returns:
        Modified XML content as bytes
    """
    try:
        # Parse the XML to extract mesh data
        root = ET.fromstring(model_content.decode('utf-8'))
        ns = {'': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
        
        # Create a completely new XML structure
        new_root = ET.Element('model')
        new_root.set('unit', 'millimeter')
        new_root.set('xml:lang', 'en-US')
        new_root.set('xmlns', 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02')
        new_root.set('xmlns:BambuStudio', 'http://schemas.bambulab.com/package/2021')
        
        # Add metadata
        metadata1 = ET.SubElement(new_root, 'metadata')
        metadata1.set('name', 'Application')
        metadata1.text = 'SVG to 3MF Converter for BambuStudio H2D'
        
        metadata2 = ET.SubElement(new_root, 'metadata')
        metadata2.set('name', 'BambuStudio:3mfVersion')
        metadata2.text = '1'
        
        metadata3 = ET.SubElement(new_root, 'metadata')
        metadata3.set('name', 'CreationDate')
        metadata3.text = '2025-07-04'
        
        resources = ET.SubElement(new_root, 'resources')
        
        # Find and process all object elements with meshes
        mesh_objects = {}
        max_id = 0
        total_faces = 0
        
        for obj in root.findall('.//object', ns):
            obj_id = int(obj.get('id', '0'))
            max_id = max(max_id, obj_id)
            
            mesh_elem = obj.find('.//mesh', ns)
            if mesh_elem is not None:
                vertices_elem = mesh_elem.find('.//vertices', ns)
                triangles_elem = mesh_elem.find('.//triangles', ns)
                
                # Count faces for statistics
                face_count = len(triangles_elem.findall('.//triangle', ns)) if triangles_elem is not None else 0
                total_faces += face_count
                
                mesh_objects[obj_id] = {
                    'vertices': vertices_elem,
                    'triangles': triangles_elem,
                    'face_count': face_count
                }
        
        # Add total face count to root
        face_count_meta = ET.SubElement(new_root, 'metadata')
        face_count_meta.set('face_count', str(total_faces))
        
        # Create new mesh objects with the correct IDs and mesh statistics
        for i, (obj_id, mesh_data) in enumerate(mesh_objects.items(), 1):
            obj_elem = ET.SubElement(resources, 'object')
            obj_elem.set('id', str(i))
            obj_elem.set('type', 'model')
            
            # Add part-specific settings as XML attributes
            if i <= len(meshes_metadata):
                metadata = meshes_metadata[i-1]
                part_name = metadata.get('name', f'Part_{i}')
                
                # Add Bambu-specific attributes for part settings
                obj_elem.set('name', part_name)
                obj_elem.set('BambuStudio:wall_loops', str(metadata.get('wall_loops', 2)))
                obj_elem.set('BambuStudio:bottom_shell_layers', str(metadata.get('bottom_shell_layers', 2)))
                
                # Add settings from HTML metadata if they exist
                if 'outer_wall_line_width' in metadata:
                    obj_elem.set('BambuStudio:outer_wall_line_width', str(metadata['outer_wall_line_width']))
                if 'inner_wall_line_width' in metadata:
                    obj_elem.set('BambuStudio:inner_wall_line_width', str(metadata['inner_wall_line_width']))
                if 'outer_wall_speed' in metadata:
                    obj_elem.set('BambuStudio:outer_wall_speed', str(metadata['outer_wall_speed']))
                if 'inner_wall_speed' in metadata:
                    obj_elem.set('BambuStudio:inner_wall_speed', str(metadata['inner_wall_speed']))
            
            mesh_elem = ET.SubElement(obj_elem, 'mesh')
            
            # Copy vertices
            vertices_elem = ET.SubElement(mesh_elem, 'vertices')
            if mesh_data['vertices'] is not None:
                for vertex in mesh_data['vertices'].findall('.//vertex', ns):
                    new_vertex = ET.SubElement(vertices_elem, 'vertex')
                    new_vertex.set('x', vertex.get('x', '0'))
                    new_vertex.set('y', vertex.get('y', '0'))
                    new_vertex.set('z', vertex.get('z', '0'))
            
            # Copy triangles
            triangles_elem = ET.SubElement(mesh_elem, 'triangles')
            if mesh_data['triangles'] is not None:
                for triangle in mesh_data['triangles'].findall('.//triangle', ns):
                    new_triangle = ET.SubElement(triangles_elem, 'triangle')
                    new_triangle.set('v1', triangle.get('v1', '0'))
                    new_triangle.set('v2', triangle.get('v2', '0'))
                    new_triangle.set('v3', triangle.get('v3', '0'))
        
        # Create the assembly object
        assembly_id = len(mesh_objects) + 1
        assembly_obj = ET.SubElement(resources, 'object')
        assembly_obj.set('id', str(assembly_id))
        assembly_obj.set('type', 'model')
        
        components = ET.SubElement(assembly_obj, 'components')
        
        # Add components with correct transforms
        for i in range(1, len(mesh_objects) + 1):
            component = ET.SubElement(components, 'component')
            component.set('objectid', str(i))
            component.set('transform', '1 0 0 0 1 0 0 0 1 0 0 0')
        
        # Add build item
        build = ET.SubElement(new_root, 'build')
        item = ET.SubElement(build, 'item')
        item.set('objectid', str(assembly_id))
        item.set('transform', '1 0 0 0 1 0 0 0 1 0 0 0')
        item.set('printable', '1')
        
        # Convert back to XML bytes
        return ET.tostring(new_root, encoding='utf-8')
    
    except Exception as e:
        print(f"Error modifying 3MF model: {str(e)}")
        # Return original content if there was an error
        return model_content

def add_bambustudio_metadata(zip_file, meshes_metadata):
    """
    Add BambuStudio metadata files to the 3MF archive
    CONVERTS TO BAMBUSTUDIO FORMAT
    
    Args:
        zip_file: Open ZipFile object in write mode
        meshes_metadata: List of dicts with mesh metadata from HTML
    """
    # Check if any mesh has printer_profile metadata
    printer_profile = "Bambu Lab H2D"
    for metadata in meshes_metadata:
        if 'printer_profile' in metadata and metadata['printer_profile']:
            printer_profile = metadata['printer_profile']
            break
    
    # Add project_settings.config in JSON format (BambuStudio expects JSON)
    project_settings = {
        "filament_colour": ["#FFFFFF", "#FF0000", "#FFFF00"],
        "filament_type": ["PC", "PC", "PC"],
        "nozzle_temperature": ["280", "280", "280"],
        "bed_temperature": ["80", "80", "80"],
        "printer_model": "Bambu Lab H2D",
        "printer_variant": "0.4",
        "printer_technology": "FFF",
        "layer_height": "0.2",
        "first_layer_height": "0.2",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "outer_wall_speed": ["300", "200", "300", "200"],
        "inner_wall_speed": ["400", "300", "400", "300"],
        "wall_loops": "2",
        "bottom_shell_layers": "4",
        "top_shell_layers": "0"
    }
    
    zip_file.writestr("Metadata/project_settings.config", json.dumps(project_settings, indent=2))
    
    # Add model_settings.config in BambuStudio format
    assembly_id = len(meshes_metadata) + 1
    
    model_settings = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="{assembly_id}">
    <metadata key="name" value="SVG_Object"/>
    <metadata key="extruder" value="1"/>
    <metadata key="printer_model" value="Bambu Lab H2D"/>
    <metadata key="printer_technology" value="FFF"/>
    <metadata key="printer_variant" value="0.4"/>
    <metadata face_count="{sum(m.get('face_count', 0) for m in meshes_metadata)}"/>
"""
    
    # Add metadata for each mesh in BambuStudio format
    for i, metadata in enumerate(meshes_metadata, 1):
        name = metadata.get('name', f"Part_{i}")
        wall_loops = metadata.get('wall_loops', 2)
        bottom_shell_layers = metadata.get('bottom_shell_layers', 2)
        face_count = metadata.get('face_count', 100)  # Default if not provided
        
        # Map filament_id to extruder correctly for H2D
        filament_id = metadata.get('filament_id', 1)
        if filament_id == 1:  # White
            extruder_id = 1
        elif filament_id == 2:  # Clear  
            extruder_id = 2
        elif filament_id == 3:  # Black
            extruder_id = 3
        else:
            extruder_id = filament_id
        
        # Calculate position matrix (simple positioning for now)
        z_pos = i * 10  # Stack vertically
        matrix = f"1 0 0 22.841823443770409 0 1 0 -49.999673709273338 0 0 1 {z_pos} 0 0 0 1"
        
        model_settings += f"""    <part id="{i}" subtype="normal_part">
      <metadata key="name" value="{name}"/>
      <metadata key="matrix" value="{matrix}"/>
      <metadata key="source_file" value="converted_svg.3mf"/>
      <metadata key="source_object_id" value="{i}"/>
      <metadata key="source_volume_id" value="{i-1}"/>
      <metadata key="source_offset_x" value="0"/>
      <metadata key="source_offset_y" value="0"/>
      <metadata key="source_offset_z" value="0"/>
      <metadata key="bottom_shell_layers" value="{bottom_shell_layers}"/>
      <metadata key="extruder" value="{extruder_id}"/>
      <metadata key="wall_loops" value="{wall_loops}"/>
"""
        
        # Add speed settings in BambuStudio 4-extruder array format
        if 'outer_wall_speed' in metadata:
            outer_wall_speed = metadata['outer_wall_speed']
            # Create 4-extruder array with speed at correct position
            speed_array = ["nil", "nil", "nil", "nil"]
            speed_array[extruder_id - 1] = str(outer_wall_speed)
            speed_str = ",".join(speed_array)
            model_settings += f"""      <metadata key="outer_wall_speed" value="{speed_str}"/>
"""
        
        if 'inner_wall_speed' in metadata:
            inner_wall_speed = metadata['inner_wall_speed']
            # Create 4-extruder array with speed at correct position
            speed_array = ["nil", "nil", "nil", "nil"]
            speed_array[extruder_id - 1] = str(inner_wall_speed)
            speed_str = ",".join(speed_array)
            model_settings += f"""      <metadata key="inner_wall_speed" value="{speed_str}"/>
"""
        
        # Add line width settings if present
        if 'outer_wall_line_width' in metadata:
            model_settings += f"""      <metadata key="outer_wall_line_width" value="{metadata['outer_wall_line_width']}"/>
"""
        
        if 'inner_wall_line_width' in metadata:
            model_settings += f"""      <metadata key="inner_wall_line_width" value="{metadata['inner_wall_line_width']}"/>
"""
        
        # Add mesh statistics in BambuStudio format
        model_settings += f"""      <mesh_stat face_count="{face_count}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
"""
    
    # Add plate section in BambuStudio format
    model_settings += f"""  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
    <model_instance>
      <metadata key="object_id" value="{assembly_id}"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="219"/>
    </model_instance>
  </plate>
  <assemble>
   <assemble_item object_id="{assembly_id}" instance_id="0" transform="1 0 0 0 1 0 0 0 1 152.15817655622959 209.99967561662197 0" offset="0 0 0" />
  </assemble>
</config>"""
    
    zip_file.writestr("Metadata/model_settings.config", model_settings)
    
    # Add slice_info.config
    slice_info = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.01.01.52"/>
  </header>
</config>"""
    
    zip_file.writestr("Metadata/slice_info.config", slice_info)

def enhance_3mf_for_orcaslicer(scene, meshes, output_file, mesh_metadata=None):
    """
    Export a scene to 3MF with BambuStudio metadata including bottom shell layers and printer profile
    
    Args:
        scene: Trimesh scene
        meshes: List of meshes with metadata
        output_file: Path to save the 3MF file
        mesh_metadata: Optional list of dicts with additional mesh metadata
    
    Returns:
        Path to the 3MF file
    """
    # If mesh_metadata is provided, use it, otherwise extract from meshes
    if mesh_metadata is None:
        mesh_metadata = []
        for mesh in meshes:
            metadata = {
                'name': mesh.metadata.get('name', 'Unknown'),
                'filament_id': mesh.metadata.get('filament_id', 1),
                'wall_loops': mesh.metadata.get('wall_loops', 2),
                'bottom_shell_layers': mesh.metadata.get('bottom_shell_layers', 2)
            }
            mesh_metadata.append(metadata)
    
    # Add face count to metadata
    for i, mesh in enumerate(meshes):
        if i < len(mesh_metadata):
            mesh_metadata[i]['face_count'] = len(mesh.faces)
    
    # Create 3MF file directly from meshes
    return create_3mf_directly(meshes, output_file, mesh_metadata)

def create_3mf_directly(meshes, output_file, mesh_metadata=None):
    """
    Create a 3MF file directly from meshes without using Trimesh's export
    
    Args:
        meshes: List of Trimesh mesh objects with metadata
        output_file: Path to save the 3MF file
        mesh_metadata: Optional list of dicts with additional mesh metadata
    
    Returns:
        Path to the created 3MF file
    """
    # Create a temporary directory for intermediate files
    with tempfile.TemporaryDirectory() as temp_dir:
        # Export meshes to STL files
        mesh_files = []
        if mesh_metadata is None:
            mesh_metadata = []
            for i, mesh in enumerate(meshes):
                metadata = {
                    'name': mesh.metadata.get('name', f"Part_{i+1}"),
                    'filament_id': mesh.metadata.get('filament_id', 1),
                    'wall_loops': mesh.metadata.get('wall_loops', 2),
                    'bottom_shell_layers': mesh.metadata.get('bottom_shell_layers', 2),
                    'face_count': len(mesh.faces)
                }
                mesh_metadata.append(metadata)
        
        for i, mesh in enumerate(meshes):
            mesh_file = os.path.join(temp_dir, f"mesh_{i}.stl")
            mesh.export(mesh_file)
            mesh_files.append(mesh_file)
        
        # Create 3MF file structure
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add [Content_Types].xml
            content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
    <Default Extension="config" ContentType="text/plain"/>
</Types>"""
            zf.writestr('[Content_Types].xml', content_types)
            
            # Add _rels/.rels
            rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/3dmodel.model" Id="rel0"/>
</Relationships>"""
            zf.writestr('_rels/.rels', rels)
            
            # Create 3D model content
            total_faces = sum(m.get('face_count', 0) for m in mesh_metadata)
            
            model_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
    <metadata name="Application">SVG to 3MF Converter for BambuStudio H2D</metadata>
    <metadata name="BambuStudio:3mfVersion">1</metadata>
    <metadata name="CreationDate">2025-07-04</metadata>
    <metadata face_count="{total_faces}"/>
    <resources>
"""
            
            # Add each mesh as an object
            for i, mesh_file in enumerate(mesh_files, 1):
                vertices, triangles = stl_to_3mf_mesh(mesh_file)
                
                vertices_xml = ""
                for x, y, z in vertices:
                    vertices_xml += f'        <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}" />\n'
                
                triangles_xml = ""
                for v1, v2, v3 in triangles:
                    triangles_xml += f'        <triangle v1="{v1}" v2="{v2}" v3="{v3}" />\n'
                
                metadata = mesh_metadata[i-1] if i-1 < len(mesh_metadata) else {}
                face_count = metadata.get('face_count', len(triangles))
                
                model_xml += f"""    <object id="{i}" type="model">
        <mesh>
            <vertices>
{vertices_xml.rstrip()}
            </vertices>
            <triangles>
{triangles_xml.rstrip()}
            </triangles>
        </mesh>
    </object>
"""
            
            # Add the assembly object
            assembly_id = len(mesh_files) + 1
            model_xml += f"""    <object id="{assembly_id}" type="model">
        <components>
"""
            
            # Add components with default transforms
            for i in range(1, len(mesh_files) + 1):
                model_xml += f'            <component objectid="{i}" transform="1 0 0 0 1 0 0 0 1 0 0 0" />\n'
            
            model_xml += f"""        </components>
    </object>
</resources>
<build>
    <item objectid="{assembly_id}" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>
</build>
</model>"""
            
            zf.writestr('3D/3dmodel.model', model_xml)
            
            # Add BambuStudio metadata
            add_bambustudio_metadata(zf, mesh_metadata)
    
    return output_file

def stl_to_3mf_mesh(stl_file):
    """
    Convert an STL file to 3MF mesh format (vertices and triangles)
    
    Args:
        stl_file: Path to STL file
    
    Returns:
        Tuple of vertices and triangles lists
    """
    import trimesh
    mesh = trimesh.load(stl_file)
    
    # Get vertices and faces
    vertices = mesh.vertices
    triangles = mesh.faces
    
    return vertices, triangles