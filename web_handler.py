import os
import json
import traceback
import http.server
import tempfile
from pathlib import Path
import zipfile
import sys
import urllib.parse
import time
from werkzeug.utils import secure_filename

# Add Shapely folder to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
shapely_dir = os.path.join(os.path.dirname(script_dir), 'Shapely')
sys.path.insert(0, shapely_dir)

# Import Shapely functionality
try:
    from Shapely import round_svg_corners
    SHAPELY_AVAILABLE = True
    print("✅ Shapely integration loaded successfully")
except ImportError as e:
    SHAPELY_AVAILABLE = False
    print(f"⚠️ Shapely not available: {e}")

# For PyQt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Import components
from path_processor import PathProcessor
from mesh_generator import MeshGenerator
from mesh_extras import enhance_3mf_for_orcaslicer

class WebRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Access-Control-Allow-Origin', '*')  # Allow CORS
            self.end_headers()
            
            # Read HTML template from file
            html_content = self.read_html_template()
            self.wfile.write(html_content.encode())
        elif self.path == '/web_handler.py':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Content-Disposition', 'attachment; filename="web_handler.py"')
            self.send_header('Access-Control-Allow-Origin', '*')  # Allow CORS
            self.end_headers()
            
            # Send the script content
            with open(__file__, 'rb') as f:
                self.wfile.write(f.read())
        elif self.path.startswith('/shapely_download/'):
            # Handle Shapely file downloads
            self.handle_shapely_download()
        else:
            self.send_error(404)
    
    def handle_shapely_download(self):
        """Handle Shapely file downloads"""
        try:
            # Extract filename from path
            filename = self.path.replace('/shapely_download/', '')
            filename = urllib.parse.unquote(filename)  # Decode URL encoding
            
            # Create uploads directory if it doesn't exist
            uploads_dir = os.path.join(tempfile.gettempdir(), 'shapely_uploads')
            os.makedirs(uploads_dir, exist_ok=True)
            
            file_path = os.path.join(uploads_dir, filename)
            
            print(f"📥 Shapely download request: {filename}")
            print(f"📍 Looking at: {os.path.abspath(file_path)}")
            print(f"📁 File exists: {os.path.exists(file_path)}")
            
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header('Content-type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                self.send_header('Access-Control-Allow-Origin', '*')
                
                # Get file size
                file_size = os.path.getsize(file_path)
                self.send_header('Content-Length', str(file_size))
                self.end_headers()
                
                # Send file content
                with open(file_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, f'File not found: {filename}')
                
        except Exception as e:
            print(f"❌ Shapely download error: {e}")
            self.send_error(500, str(e))
    
    def read_html_template(self):
        """Read HTML template from file"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, "template.html")
        
        try:
            with open(template_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            print(f"Error reading template file: {str(e)}")
            return "<html><body><h1>Error: Could not load template</h1><p>Please ensure template.html exists in the application directory.</p></body></html>"
    
    def do_OPTIONS(self):
        # Handle preflight requests for CORS
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_POST(self):
        if self.path == '/generate':
            self.handle_claudia_generate()
        elif self.path == '/shapely_convert':
            self.handle_shapely_convert()
        else:
            self.send_error(404)
    
    def handle_claudia_generate(self):
        """Handle /generate route - NOW USES TWO SEPARATE SVG FILES"""
        try:
            # Get content length
            content_length = int(self.headers['Content-Length'])
            
            # Set a reasonable maximum size limit
            if content_length > 10 * 1024 * 1024:  # 10MB limit
                self.send_error(413, "Request entity too large")
                return
            
            # Parse the multipart form data
            ctype = self.headers['Content-Type']
            
            if not ctype.startswith('multipart/form-data'):
                self.send_error(400, "Invalid content type")
                return
            
            # Get boundary
            boundary = None
            for part in ctype.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[9:]
                    if boundary.startswith('"') and boundary.endswith('"'):
                        boundary = boundary[1:-1]
                    break
            
            if not boundary:
                self.send_error(400, "No boundary found")
                return
            
            # Read the form data
            form_data = self.rfile.read(content_length)
            
            # NEW: Process the form data for TWO SVG files
            return_svg_data, white_svg_data, params_data = self.extract_dual_form_data(form_data, boundary.encode())
            
            if not return_svg_data or not white_svg_data or not params_data:
                self.send_error(400, "Missing required data - need both return and white SVG files")
                return
            
            # Parse JSON parameters
            params = json.loads(params_data)
            
            # For debugging - print the layer settings
            print("Layer settings received from interface:", json.dumps(params.get('layerSettings', []), indent=2))
            print("Bottom shell layers:", params.get('bottomShellLayers', 2))
            print("Printer profile:", params.get('printerProfile', 'Default'))
            
            # Save BOTH SVG files to temporary files
            temp_return_svg_path = self.save_svg_to_temp_file(return_svg_data, "return")
            temp_white_svg_path = self.save_svg_to_temp_file(white_svg_data, "white")
            
            # Process SVG files
            output_file_path = self.process_dual_svg_files(temp_return_svg_path, temp_white_svg_path, params)
            
            # Read the 3MF file and send it back
            with open(output_file_path, 'rb') as f:
                output_data = f.read()
            
            # Clean up temporary files
            if os.path.exists(temp_return_svg_path):
                os.remove(temp_return_svg_path)
            if os.path.exists(temp_white_svg_path):
                os.remove(temp_white_svg_path)
            
            # Send the response
            self.send_response(200)
            
            # NEW: Set different content type for ZIP files
            if output_file_path.endswith('.zip'):
                self.send_header('Content-type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename="separate_objects.zip"')
            else:
                self.send_header('Content-type', 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment; filename="output.3mf"')
            
            self.send_header('Content-Length', str(len(output_data)))
            self.send_header('Access-Control-Allow-Origin', '*')  # Allow CORS
            self.end_headers()
            self.wfile.write(output_data)
            
        except Exception as e:
            print(f"Error processing request: {str(e)}")
            traceback.print_exc()
            self.send_error(500, str(e))
    
    def handle_shapely_convert(self):
        """Handle Shapely's /convert route - NOW CREATES 3 FILES"""
        if not SHAPELY_AVAILABLE:
            self.send_json_response({'success': False, 'error': 'Shapely functionality not available'})
            return
        
        try:
            print("🔄 Starting Shapely SVG conversion process...")
            
            # Get content length
            content_length = int(self.headers['Content-Length'])
            
            # Parse the multipart form data
            ctype = self.headers['Content-Type']
            
            if not ctype.startswith('multipart/form-data'):
                self.send_json_response({'success': False, 'error': 'Invalid content type'})
                return
            
            # Get boundary
            boundary = None
            for part in ctype.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[9:]
                    if boundary.startswith('"') and boundary.endswith('"'):
                        boundary = boundary[1:-1]
                    break
            
            if not boundary:
                self.send_json_response({'success': False, 'error': 'No boundary found'})
                return
            
            # Read the form data
            form_data = self.rfile.read(content_length)
            
            # NEW: Extract Shapely form data including white_offset
            file_data, offset, corner, white_offset, resolution = self.extract_shapely_form_data(form_data, boundary.encode())
            
            if not file_data:
                self.send_json_response({'success': False, 'error': 'No file uploaded'})
                return
            
            print(f"⚙️ Shapely settings: offset={offset}mm, corner={corner}mm, white_offset={white_offset}mm, resolution={resolution}")
            
            # Create uploads directory
            uploads_dir = os.path.join(tempfile.gettempdir(), 'shapely_uploads')
            os.makedirs(uploads_dir, exist_ok=True)
            
            # Save uploaded file
            filename = f"input_{int(time.time())}.svg"
            input_path = os.path.join(uploads_dir, filename)
            
            with open(input_path, 'wb') as f:
                f.write(file_data)
            
            print(f"💾 Shapely file saved to: {input_path}")
            
            # Create Face file (offset=0, corner=corner)
            face_filename = f"face_{filename}"
            face_path = os.path.join(uploads_dir, face_filename)
            
            print("📄 Creating FACE file...")
            face_success = round_svg_corners(
                input_path, 
                face_path, 
                offset=0, 
                corner_radius=corner, 
                curve_resolution=resolution
            )
            
            # Create Return file (offset=offset, corner=corner+offset) - BLACK PARTS
            return_filename = f"return_{filename}"
            return_path = os.path.join(uploads_dir, return_filename)
            
            print("🔄 Creating RETURN file (for black parts)...")
            return_success = round_svg_corners(
                input_path, 
                return_path, 
                offset=offset, 
                corner_radius=corner + offset, 
                curve_resolution=resolution
            )
            
            # NEW: Create White file (offset=white_offset, corner=corner+offset) - WHITE PARTS
            white_filename = f"white_{filename}"
            white_path = os.path.join(uploads_dir, white_filename)
            
            print(f"⚪ Creating WHITE file (for white parts) with {white_offset}mm offset...")
            white_success = round_svg_corners(
                input_path, 
                white_path, 
                offset=white_offset, 
                corner_radius=corner + offset, 
                curve_resolution=resolution
            )
            
            if not face_success or not return_success or not white_success:
                self.send_json_response({'success': False, 'error': 'SVG processing failed'})
                return
            
            # Read all THREE SVG files for preview
            face_svg_content = ""
            return_svg_content = ""
            
            try:
                if os.path.exists(face_path):
                    with open(face_path, 'r') as f:
                        face_svg_content = f.read()
                    print(f"✅ Face SVG loaded: {face_path}")
                else:
                    print(f"⚠️ Face file not found: {face_path}")
                
                if os.path.exists(return_path):
                    with open(return_path, 'r') as f:
                        return_svg_content = f.read()
                    print(f"✅ Return SVG loaded: {return_path}")
                else:
                    print(f"⚠️ Return file not found: {return_path}")
                
                if os.path.exists(white_path):
                    print(f"✅ White SVG created: {white_path}")
                else:
                    print(f"⚠️ White file not found: {white_path}")
                    
            except Exception as read_error:
                print(f"Warning: Could not read SVG files for preview: {read_error}")
                face_svg_content = "<svg><text>Face preview not available</text></svg>"
                return_svg_content = "<svg><text>Return preview not available</text></svg>"
            
            print("✅ Shapely SVG processed successfully - 3 files created")
            
            # NEW: Send success response with all THREE filenames
            self.send_json_response({
                'success': True,
                'face_svg_content': face_svg_content,
                'return_svg_content': return_svg_content,
                'face_filename': face_filename,
                'return_filename': return_filename,
                'white_filename': white_filename,  # NEW: Third file for white parts
                'message': f"Processed {filename} successfully - 3 files created"
            })
            
        except Exception as e:
            print(f"❌ Shapely conversion error: {e}")
            traceback.print_exc()
            self.send_json_response({'success': False, 'error': str(e)})
    
    def extract_shapely_form_data(self, form_data, boundary):
        """Extract Shapely form data including WHITE OFFSET parameter"""
        file_data = None
        offset = 0.5  # Default to match UI
        corner = 1.0  # Default to match UI
        white_offset = -1.0  # NEW: Default white offset
        resolution = 40  # Default to match UI
        
        try:
            # Split the form data into parts
            parts = form_data.split(b'--' + boundary)
            
            for part in parts:
                if b'name="file"' in part:
                    # Extract the file content
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        file_data = part[content_idx + 4:]
                        if file_data.endswith(b'\r\n'):
                            file_data = file_data[:-2]
                
                elif b'name="offset"' in part:
                    # Extract offset value
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        offset_str = part[content_idx + 4:].decode('utf-8').strip()
                        if offset_str.endswith('\r\n'):
                            offset_str = offset_str[:-2]
                        try:
                            offset = float(offset_str)
                        except ValueError:
                            pass
                
                elif b'name="corner"' in part:
                    # Extract corner value
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        corner_str = part[content_idx + 4:].decode('utf-8').strip()
                        if corner_str.endswith('\r\n'):
                            corner_str = corner_str[:-2]
                        try:
                            corner = float(corner_str)
                        except ValueError:
                            pass
                
                elif b'name="white_offset"' in part:
                    # NEW: Extract white_offset value
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        white_offset_str = part[content_idx + 4:].decode('utf-8').strip()
                        if white_offset_str.endswith('\r\n'):
                            white_offset_str = white_offset_str[:-2]
                        try:
                            white_offset = float(white_offset_str)
                        except ValueError:
                            pass
                
                elif b'name="resolution"' in part:
                    # Extract resolution value
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        resolution_str = part[content_idx + 4:].decode('utf-8').strip()
                        if resolution_str.endswith('\r\n'):
                            resolution_str = resolution_str[:-2]
                        try:
                            resolution = int(resolution_str)
                        except ValueError:
                            pass
            
            print(f"Shapely data extracted: {len(file_data) if file_data else 0} bytes")
            print(f"Parameters: offset={offset}, corner={corner}, white_offset={white_offset}, resolution={resolution}")
            
            return file_data, offset, corner, white_offset, resolution
        
        except Exception as e:
            print(f"Error extracting Shapely form data: {str(e)}")
            return None, 0.5, 1.0, -1.0, 40  # Fallback defaults
    
    def send_json_response(self, data):
        """Send JSON response"""
        response_json = json.dumps(data)
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(response_json)))
        self.end_headers()
        self.wfile.write(response_json.encode())
    
    def extract_dual_form_data(self, form_data, boundary):
        """Extract TWO SVG files and JSON data from the form data"""
        return_svg_data = None
        white_svg_data = None
        params_data = None
        
        try:
            # Split the form data into parts
            parts = form_data.split(b'--' + boundary)
            
            for part in parts:
                if b'name="returnSvgFile"' in part:
                    # Extract the return SVG file content
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        return_svg_data = part[content_idx + 4:]
                        if return_svg_data.endswith(b'\r\n'):
                            return_svg_data = return_svg_data[:-2]
                
                elif b'name="whiteSvgFile"' in part:
                    # NEW: Extract the white SVG file content
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        white_svg_data = part[content_idx + 4:]
                        if white_svg_data.endswith(b'\r\n'):
                            white_svg_data = white_svg_data[:-2]
                
                elif b'name="data"' in part:
                    # Extract the JSON data
                    content_idx = part.find(b'\r\n\r\n')
                    if content_idx > 0:
                        params_data = part[content_idx + 4:].decode('utf-8')
                        if params_data.endswith('\r\n'):
                            params_data = params_data[:-2]
            
            print(f"Return SVG data extracted: {len(return_svg_data) if return_svg_data else 0} bytes")
            print(f"White SVG data extracted: {len(white_svg_data) if white_svg_data else 0} bytes")
            print(f"JSON data extracted: {params_data}")
            
            return return_svg_data, white_svg_data, params_data
        
        except Exception as e:
            print(f"Error extracting dual form data: {str(e)}")
            raise
    
    def save_svg_to_temp_file(self, svg_data, prefix="svg"):
        """Save SVG data to a temporary file"""
        try:
            with tempfile.NamedTemporaryFile(suffix=f"_{prefix}.svg", delete=False) as tmp_file:
                tmp_file.write(svg_data)
                temp_path = tmp_file.name
            
            print(f"{prefix.upper()} SVG saved to temporary file: {temp_path}")
            return temp_path
        except Exception as e:
            print(f"Error saving {prefix} SVG to temp file: {str(e)}")
            raise

    def process_dual_svg_files(self, return_svg_path, white_svg_path, params):
        """Process TWO SVG files to create 3MF file(s) - WITH SEPARATE OBJECTS SUPPORT & LAYER SETTINGS"""
        import trimesh
        from lxml import etree
        from svgpathtools import parse_path
        
        try:
            # Get layer settings
            layer_settings = params['layerSettings']
            
            # NEW: Get printing mode (no longer need X offset for separate mode)
            printing_mode = params.get('printingMode', 'combined')
            
            print(f"🎯 Printing mode: {printing_mode}")
            if printing_mode == 'separate':
                print(f"📁 Will create two separate 3MF files in ZIP")
            
            # Get bottom shell layers from Inside_floor
            bottom_shell_layers = int(params.get('bottomShellLayers', 2))
            print(f"Using bottom shell layers: {bottom_shell_layers}")
            
            # Get printer profile
            printer_profile = params.get('printerProfile', '')
            print(f"Using printer profile: {printer_profile}")
            
            # Layer mapping
            layer_mapping = {
                "Inside_floor": "Inside_floor",
                "Inside_white": "Inside_white",
                "Inside_white_top": "Inside_white_top",
                "Return_floor": "Return_bottom",
                "Return_top": "Return_top",
                "Return_top2": "Return_top2",
                "Return_top3": "Return_top3"
            }
            
            # Initialize heights and settings
            inside_floor_height = 0
            inside_height = 0
            inside_white_top_height = 0
            bottom_height = 0
            top_height = 0
            top2_height = 0
            top3_height = 0
            top3_enabled = True
            inside_white_top_enabled = True
            
            filament_ids = {}
            wall_loops_data = {}
            layer_specific_settings = {}  # NEW: Store layer-specific settings
            
            # FIXED: Process layer settings with additional parameters
            for layer in layer_settings:
                name = layer.get('name', '')
                height = float(layer.get('height', 10.0))
                filament = int(layer.get('filament', 1))
                walls = int(layer.get('wallLoops', 2))
                enabled = layer.get('enabled', True)
                
                # NEW: Extract layer-specific settings
                outer_wall_line_width = layer.get('outerWallLineWidth')
                inner_wall_line_width = layer.get('innerWallLineWidth')
                outer_wall_speed = layer.get('outerWallSpeed')
                inner_wall_speed = layer.get('innerWallSpeed')
                
                print(f"Layer: {name}, Height: {height}, Filament: {filament}, Wall Loops: {walls}, Enabled: {enabled}")
                if outer_wall_line_width:
                    print(f"  → Outer Wall Line Width: {outer_wall_line_width}mm")
                if inner_wall_line_width:
                    print(f"  → Inner Wall Line Width: {inner_wall_line_width}mm")
                if outer_wall_speed:
                    print(f"  → Outer Wall Speed: {outer_wall_speed}mm/s")
                if inner_wall_speed:
                    print(f"  → Inner Wall Speed: {inner_wall_speed}mm/s")
                
                if name in layer_mapping:
                    v179_name = layer_mapping[name]
                    filament_ids[v179_name] = filament
                    wall_loops_data[v179_name] = walls
                    
                    # NEW: Store layer-specific settings
                    if outer_wall_line_width or inner_wall_line_width or outer_wall_speed or inner_wall_speed:
                        layer_specific_settings[v179_name] = {}
                        if outer_wall_line_width:
                            layer_specific_settings[v179_name]['outerWallLineWidth'] = float(outer_wall_line_width)
                        if inner_wall_line_width:
                            layer_specific_settings[v179_name]['innerWallLineWidth'] = float(inner_wall_line_width)
                        if outer_wall_speed:
                            layer_specific_settings[v179_name]['outerWallSpeed'] = float(outer_wall_speed)
                        if inner_wall_speed:
                            layer_specific_settings[v179_name]['innerWallSpeed'] = float(inner_wall_speed)
                    
                    # Set heights based on layer name
                    if name == "Inside_floor":
                        inside_floor_height = height
                    elif name == "Inside_white":
                        inside_height = height
                    elif name == "Inside_white_top":
                        inside_white_top_height = height
                        inside_white_top_enabled = enabled
                    elif name == "Return_floor":
                        bottom_height = height
                    elif name == "Return_top":
                        top_height = height
                    elif name == "Return_top2":
                        top2_height = height
                    elif name == "Return_top3":
                        top3_height = height
                        top3_enabled = enabled
            
            print(f"Filament IDs: {filament_ids}")
            print(f"Wall loops data: {wall_loops_data}")
            print(f"Layer-specific settings: {layer_specific_settings}")
            
            # Process SVG
            path_processor = PathProcessor()
            
            # Create custom MeshGenerator with wall loops data and layer-specific settings
            class CustomMeshGenerator:
                def __init__(self, wall_loops_data, bottom_shell_layers, layer_specific_settings):
                    self.wall_loops_data = wall_loops_data
                    self.bottom_shell_layers = bottom_shell_layers
                    self.layer_specific_settings = layer_specific_settings
                    self.mesh_generator = MeshGenerator()
                
                def extrude_path(self, points, height, z_offset, name, filament_id):
                    # Extract base name for lookup
                    base_name = name.split('_letter')[0] if '_letter' in name else name
                    
                    # Get wall loops from our data
                    wall_loops = self.wall_loops_data.get(base_name, 2)
                    
                    print(f"Using wall loops {wall_loops} for {name}")
                    
                    # Create mesh using MeshGenerator
                    mesh = self.mesh_generator.extrude_path(
                        points, height, z_offset, name, filament_id
                    )
                    
                    # Add metadata
                    if mesh is not None:
                        if not hasattr(mesh, 'metadata'):
                            mesh.metadata = {}
                        mesh.metadata['wall_loops'] = wall_loops
                        
                        # ✅ FIXED: Add layer-specific settings to metadata with correct key conversion
                        if base_name in self.layer_specific_settings:
                            # KEY MAPPING FIX - Convert camelCase to snake_case correctly
                            key_mapping = {
                                'outerWallLineWidth': 'outer_wall_line_width',
                                'innerWallLineWidth': 'inner_wall_line_width', 
                                'outerWallSpeed': 'outer_wall_speed',
                                'innerWallSpeed': 'inner_wall_speed'
                            }
                            
                            for key, value in self.layer_specific_settings[base_name].items():
                                correct_key = key_mapping.get(key, key.lower())  # Use mapping or fallback
                                mesh.metadata[correct_key] = value
                                print(f"✅ FIXED: Added {correct_key}={value} to {name}")
                        
                        # Add bottom_shell_layers for Inside layers
                        if base_name in ["Inside_floor", "Inside_white", "Inside_white_top"]:
                            mesh.metadata["bottom_shell_layers"] = self.bottom_shell_layers
                            print(f"Added bottom_shell_layers={self.bottom_shell_layers} to {name}")
                    
                    return mesh
            
            mesh_generator = CustomMeshGenerator(wall_loops_data, bottom_shell_layers, layer_specific_settings)
            
            # ===============================================================================
            # 🎯 CLEAN SIMPLE LOGIC - USE SHAPELY FILES DIRECTLY
            # ===============================================================================
            
            print(f"🎯 Using Shapely files directly - Perfect gap guaranteed!")
            print(f"Return file: {return_svg_path} → Black/Clear parts (larger)")
            print(f"White file: {white_svg_path} → White parts (smaller)")
            
            # Parse both SVG files directly - NO COMPLEX PROCESSING
            parser = etree.XMLParser(remove_blank_text=True)
            tree_return = etree.parse(return_svg_path, parser)  # For Return layers (black/clear)
            tree_white = etree.parse(white_svg_path, parser)    # For Inside layers (white)
            
            # Process Return SVG (for black/clear parts)
            namespaces = {"svg": "http://www.w3.org/2000/svg"}
            svg_root_return = tree_return.getroot()
            viewBox_return = svg_root_return.get("viewBox")
            width_return = svg_root_return.get("width", "132.04")
            height_svg_return = svg_root_return.get("height", "200.49")
            
            if isinstance(width_return, str):
                width_return = float(width_return.replace("mm", "").strip())
            else:
                width_return = float(width_return)
            
            if isinstance(height_svg_return, str):
                height_svg_return = float(height_svg_return.replace("mm", "").strip())
            else:
                height_svg_return = float(height_svg_return)
            
            scale_factor_return = 1.0
            if viewBox_return:
                vb_vals = [float(v) for v in viewBox_return.split()]
                if vb_vals[2] != 0 and vb_vals[3] != 0:
                    scale_factor_return = min(width_return / vb_vals[2], height_svg_return / vb_vals[3])
            
            # Process White SVG (use same scale factor)
            scale_factor_white = scale_factor_return
            
            # Convert polygons to paths in both SVGs
            for tree, name in [(tree_return, "Return"), (tree_white, "White")]:
                polygons = tree.xpath("//svg:polygon", namespaces=namespaces)
                for polygon in polygons:
                    points = polygon.get("points")
                    if not points:
                        continue
                    d = path_processor.polygon_to_path_d(points)
                    if d:
                        path = etree.SubElement(tree.getroot(), "{http://www.w3.org/2000/svg}path")
                        path.set("d", d)
                        path.set("fill", polygon.get("fill", "#ffa500"))
                        path.set("fill-rule", polygon.get("fill-rule", "evenodd"))
                        tree.getroot().remove(polygon)
            
            # Get paths from both SVGs
            paths_return = tree_return.xpath("//svg:path", namespaces=namespaces)
            paths_white = tree_white.xpath("//svg:path", namespaces=namespaces)
            
            if not paths_return:
                raise ValueError("No valid paths found in Return SVG.")
                
            if not paths_white:
                raise ValueError("No valid paths found in White SVG.")
            
            # Process all shapes and create meshes
            all_meshes = []
            shape_count = 0
            
            print(f"🔤 Processing {len(paths_return)} Return shapes and {len(paths_white)} White shapes")
            
            # ===============================================================================
            # POSITIONING LOGIC - SIMPLIFIED FOR SEPARATE MODE
            # ===============================================================================
            
            # For separate mode: Both parts at (0,0) but in separate files
            # For combined mode: Both parts at (0,0) overlapping in same file
            return_x_offset = 0.0  # Return parts always at origin
            white_x_offset = 0.0   # White parts always at origin
            
            if printing_mode == 'separate':
                print(f"🔄 SEPARATE MODE: Creating two separate 3MF files")
            else:
                print(f"🔄 COMBINED MODE: Both parts overlapping in single file")
            
            # ===============================================================================
            
            # Process Return shapes for Return layers (black, clear - from return file)
            for i, path in enumerate(paths_return):
                d = path.get("d")
                if not d:
                    continue
                    
                path_obj = parse_path(d)
                points = path_processor.sample_bezier_path(path_obj, samples_per_segment=20)
                
                if len(points) < 3:
                    continue
                
                # NEW: Apply positioning (both at origin now for separate files)
                scaled_points = [
                    [point[0] * scale_factor_return + return_x_offset, point[1] * scale_factor_return] 
                    for point in points
                ]
                
                shape_count += 1
                print(f"🔄 Letter {shape_count} (Return - From return file)")
                
                # Create Return layers
                
                # 1. Return_bottom (black)
                bottom_filament = filament_ids.get("Return_bottom", 3)
                bottom_mesh = mesh_generator.extrude_path(
                    scaled_points, 
                    bottom_height, 
                    z_offset=0.0, 
                    name=f"Return_bottom_letter{shape_count}", 
                    filament_id=bottom_filament
                )
                if bottom_mesh is not None:
                    all_meshes.append(bottom_mesh)
                
                # 2. Return_top (black)
                top_filament = filament_ids.get("Return_top", 3)
                top_mesh = mesh_generator.extrude_path(
                    scaled_points, 
                    top_height, 
                    z_offset=bottom_height, 
                    name=f"Return_top_letter{shape_count}", 
                    filament_id=top_filament
                )
                if top_mesh is not None:
                    all_meshes.append(top_mesh)
                
                # 3. Return_top2 (black)
                if top2_height > 0:
                    top2_filament = filament_ids.get("Return_top2", 3)
                    top2_z_offset = bottom_height + top_height
                    
                    top2_mesh = mesh_generator.extrude_path(
                        scaled_points,
                        top2_height,
                        z_offset=top2_z_offset,
                        name=f"Return_top2_letter{shape_count}",
                        filament_id=top2_filament
                    )
                    if top2_mesh is not None:
                        all_meshes.append(top2_mesh)
                
                # 4. Return_top3 (black - only if enabled)
                if top3_height > 0 and top3_enabled:
                    top3_filament = filament_ids.get("Return_top3", 3)
                    top3_z_offset = bottom_height + top_height + top2_height
                    
                    top3_mesh = mesh_generator.extrude_path(
                        scaled_points,
                        top3_height,
                        z_offset=top3_z_offset,
                        name=f"Return_top3_letter{shape_count}",
                        filament_id=top3_filament
                    )
                    
                    if top3_mesh is not None:
                        all_meshes.append(top3_mesh)
            
            # Process White shapes for Inside layers (white - from white file)
            white_shape_count = 0
            for i, path in enumerate(paths_white):
                d = path.get("d")
                if not d:
                    continue
                    
                path_obj = parse_path(d)
                points = path_processor.sample_bezier_path(path_obj, samples_per_segment=20)
                
                if len(points) < 3:
                    continue
                
                # NEW: Apply positioning (both at origin now for separate files)
                scaled_points = [
                    [point[0] * scale_factor_white + white_x_offset, point[1] * scale_factor_white] 
                    for point in points
                ]
                
                white_shape_count += 1
                print(f"📝 Letter {white_shape_count} (White - From white file)")
                
                # Create Inside layers
                
                # 1. Inside_floor (white - bottom layer)
                if inside_floor_height > 0:
                    inside_floor_filament = filament_ids.get("Inside_floor", 1)
                    
                    # Get z_offset from layer settings
                    inside_floor_layer_settings = next((layer for layer in layer_settings if layer.get('name') == 'Inside_floor'), None)
                    inside_floor_z_offset = float(inside_floor_layer_settings.get('zOffset', 0.2)) if inside_floor_layer_settings else 0.2
    
                    inside_floor_mesh = mesh_generator.extrude_path(
                        scaled_points, 
                        inside_floor_height,
                        z_offset=inside_floor_z_offset,
                        name=f"Inside_floor_letter{white_shape_count}", 
                        filament_id=inside_floor_filament
                    )
                    
                    if inside_floor_mesh is not None:
                        all_meshes.append(inside_floor_mesh)
                
                # 2. Inside_white (white - walls layer)
                if inside_height > 0:
                    inside_filament = filament_ids.get("Inside_white", 1)
                    inside_mesh = mesh_generator.extrude_path(
                        scaled_points, 
                        inside_height,
                        z_offset=inside_floor_height + 0.1,
                        name=f"Inside_white_letter{white_shape_count}", 
                        filament_id=inside_filament
                    )
                    
                    if inside_mesh is not None:
                        all_meshes.append(inside_mesh)
                
                # 3. Inside_white_top (white - only if enabled)
                if inside_white_top_height > 0 and inside_white_top_enabled:
                    inside_white_top_filament = filament_ids.get("Inside_white_top", 1)
                    inside_white_top_z_offset = inside_floor_height + 0.1 + inside_height
                    
                    inside_white_top_mesh = mesh_generator.extrude_path(
                        scaled_points,
                        inside_white_top_height,
                        z_offset=inside_white_top_z_offset,
                        name=f"Inside_white_top_letter{white_shape_count}",
                        filament_id=inside_white_top_filament
                    )
                    
                    if inside_white_top_mesh is not None:
                        all_meshes.append(inside_white_top_mesh)
            
            if printing_mode == 'separate':
                print(f"✅ SEPARATE objects processing complete: {shape_count} Return + {white_shape_count} White shapes, {len(all_meshes)} total meshes")
                print(f"🎯 Creating TWO separate 3MF files...")
                
                # Separate meshes into Return and White groups
                return_meshes = []
                white_meshes = []
                
                for mesh in all_meshes:
                    mesh_name = mesh.metadata.get('name', '')
                    if 'Return_' in mesh_name:
                        return_meshes.append(mesh)
                    elif 'Inside_' in mesh_name:
                        white_meshes.append(mesh)
                
                if not return_meshes or not white_meshes:
                    raise ValueError("Missing Return or White meshes for separate mode!")
                
                # Create separate 3MF files
                base_filename = str(Path(return_svg_path).stem)
                
                # 1. Create Return 3MF file
                return_scene = trimesh.Scene()
                for mesh in return_meshes:
                    return_scene.add_geometry(mesh)
                
                return_output_file = str(Path(return_svg_path).parent / f"{base_filename}_return.3mf")
                
                # Extract Return mesh metadata
                return_metadata = []
                for mesh in return_meshes:
                    metadata = {
                        'name': mesh.metadata.get('name', 'Unknown'),
                        'filament_id': mesh.metadata.get('filament_id', 3),
                        'wall_loops': mesh.metadata.get('wall_loops', 2)
                    }
                    
                    # NEW: Add layer-specific settings to metadata - FIXED KEY NAMES
                    base_mesh_name = metadata['name']
                    if '_letter' in base_mesh_name:
                        base_mesh_name = base_mesh_name.split('_letter')[0]
                    
                    for key in ['outer_wall_line_width', 'inner_wall_line_width', 'outer_wall_speed', 'inner_wall_speed']:
                        if key in mesh.metadata:
                            metadata[key] = mesh.metadata[key]
                    
                    if printer_profile:
                        metadata['printer_profile'] = printer_profile
                    
                    return_metadata.append(metadata)
                
                enhance_3mf_for_orcaslicer(return_scene, return_meshes, return_output_file, return_metadata)
                print(f"✅ Return 3MF created: {return_output_file}")
                
                # 2. Create White 3MF file
                white_scene = trimesh.Scene()
                for mesh in white_meshes:
                    white_scene.add_geometry(mesh)
                
                white_output_file = str(Path(return_svg_path).parent / f"{base_filename}_white.3mf")
                
                # Extract White mesh metadata
                white_metadata = []
                for mesh in white_meshes:
                    metadata = {
                        'name': mesh.metadata.get('name', 'Unknown'),
                        'filament_id': mesh.metadata.get('filament_id', 1),
                        'wall_loops': mesh.metadata.get('wall_loops', 2)
                    }
                    
                    # Add bottom_shell_layers if present
                    if 'bottom_shell_layers' in mesh.metadata:
                        metadata['bottom_shell_layers'] = mesh.metadata['bottom_shell_layers']
                    
                    # NEW: Add layer-specific settings to metadata - FIXED KEY NAMES
                    base_mesh_name = metadata['name']
                    if '_letter' in base_mesh_name:
                        base_mesh_name = base_mesh_name.split('_letter')[0]
                    
                    for key in ['outer_wall_line_width', 'inner_wall_line_width', 'outer_wall_speed', 'inner_wall_speed']:
                        if key in mesh.metadata:
                            metadata[key] = mesh.metadata[key]
                    
                    if printer_profile:
                        metadata['printer_profile'] = printer_profile
                    
                    white_metadata.append(metadata)
                
                enhance_3mf_for_orcaslicer(white_scene, white_meshes, white_output_file, white_metadata)
                print(f"✅ White 3MF created: {white_output_file}")
                
                # 3. Create ZIP file containing both 3MF files - FIXED: Clean filenames inside ZIP
                zip_output_file = str(Path(return_svg_path).parent / f"{base_filename}_separate.zip")
                
                with zipfile.ZipFile(zip_output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # FIXED: Use clean names inside ZIP
                    zipf.write(return_output_file, "Return.3mf")
                    zipf.write(white_output_file, "White.3mf")
                    
                    # Add README file
                    readme_content = f"""Separate 3MF Files for Lockletter

This ZIP contains two separate 3MF files:

1. Return.3mf - Black/Clear Return parts
   - Filament: Black or Clear
   - Contains outer structure

2. White.3mf - White Inside parts  
   - Filament: White
   - Contains inner structure

Instructions:
- Load each file separately into your slicer
- Print both objects
- The white part fits inside the return part
- Perfect gap guaranteed by Shapely processing

Generated by Lockletter v179"""
                    
                    zipf.writestr("README.txt", readme_content)
                
                # Clean up individual 3MF files
                if os.path.exists(return_output_file):
                    os.remove(return_output_file)
                if os.path.exists(white_output_file):
                    os.remove(white_output_file)
                
                print(f"✅ ZIP file with separate 3MFs created: {zip_output_file}")
                return zip_output_file
                
            else:
                print(f"✅ COMBINED objects processing complete: {shape_count} Return + {white_shape_count} White shapes, {len(all_meshes)} total meshes")
                print(f"✅ Perfect gap guaranteed - Shapely created the offset!")
                
                if not all_meshes:
                    raise ValueError("No valid meshes to export!")
                
                # Create scene and export single combined 3MF
                scene = trimesh.Scene()
                for mesh in all_meshes:
                    scene.add_geometry(mesh)
                
                # Export to 3MF
                output_file = str(Path(return_svg_path).with_suffix(".3mf"))
                
                # Extract mesh metadata
                mesh_metadata = []
                for mesh in all_meshes:
                    metadata = {
                        'name': mesh.metadata.get('name', 'Unknown'),
                        'filament_id': mesh.metadata.get('filament_id', 1),
                        'wall_loops': mesh.metadata.get('wall_loops', 2)
                    }
                    
                    # Add bottom_shell_layers if present
                    if 'bottom_shell_layers' in mesh.metadata:
                        metadata['bottom_shell_layers'] = mesh.metadata['bottom_shell_layers']
                    
                    # NEW: Add layer-specific settings to metadata - FIXED KEY NAMES
                    base_mesh_name = metadata['name']
                    if '_letter' in base_mesh_name:
                        base_mesh_name = base_mesh_name.split('_letter')[0]
                    
                    for key in ['outer_wall_line_width', 'inner_wall_line_width', 'outer_wall_speed', 'inner_wall_speed']:
                        if key in mesh.metadata:
                            metadata[key] = mesh.metadata[key]
                    
                    if printer_profile:
                        metadata['printer_profile'] = printer_profile
                    
                    mesh_metadata.append(metadata)
                
                # Use enhanced 3MF function
                enhance_3mf_for_orcaslicer(scene, all_meshes, output_file, mesh_metadata)
                
                print(f"✅ Combined 3MF file generated: {output_file}")
                return output_file
            
        except Exception as e:
            print(f"Error processing dual SVG files: {str(e)}")
            traceback.print_exc()
            raise