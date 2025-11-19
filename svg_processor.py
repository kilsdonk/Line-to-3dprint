from lxml import etree
import tempfile
import os
from svgpathtools import parse_path, Path
import pyclipper
from path_processor import PathProcessor

class SvgProcessor:
    def __init__(self):
        self.path_processor = PathProcessor()
    
    def generate_offset_svg(self, file_path, offset_mm=1.0):
        """
        Generate an offset SVG file with simplified logic - no winding complexity
        
        Args:
            file_path: Path to input SVG file
            offset_mm: Offset in millimeters (negative = smaller, positive = larger)
            
        Returns:
            Path to temporary offset SVG file, or None if failed
        """
        try:
            tree = etree.parse(file_path)
        except Exception as e:
            print(f"Error parsing SVG file {file_path}: {str(e)}")
            return None

        svg_root = tree.getroot()
        svg_root.set("version", "1.1")
        if "xmlns" not in svg_root.attrib:
            svg_root.set("xmlns", "http://www.w3.org/2000/svg")

        width = svg_root.get("width", "100mm")
        height = svg_root.get("height", "100mm")
        viewBox = svg_root.get("viewBox", "0 0 100 100")

        # Scaling factor for precision
        SCALE = 1000
        delta = SCALE * offset_mm  # Convert mm to scaled units
        
        print(f"🔧 SVG Offset: {offset_mm}mm (delta: {delta})")

        # Find all paths and polygons
        paths = svg_root.findall(".//{http://www.w3.org/2000/svg}path")
        polygons = svg_root.findall(".//{http://www.w3.org/2000/svg}polygon")
        
        if not paths and not polygons:
            print("❌ No paths or polygons found in SVG file.")
            return None

        # Convert polygons to paths first
        for polygon in polygons:
            points = polygon.get("points")
            if not points:
                print("⚠️ Warning: Polygon element has no 'points' attribute.")
                continue
                
            d = self.path_processor.polygon_to_path_d(points)
            if d:
                # Create new path element
                path = etree.SubElement(svg_root, "{http://www.w3.org/2000/svg}path")
                path.set("d", d)
                path.set("fill", polygon.get("fill", "#ffa500"))
                path.set("fill-rule", polygon.get("fill-rule", "evenodd"))
                # Remove original polygon
                svg_root.remove(polygon)
                print(f"✅ Converted polygon to path")

        # Get all paths (including converted polygons)
        paths = svg_root.findall(".//{http://www.w3.org/2000/svg}path")
        if not paths:
            print("❌ No paths found after processing polygons.")
            return None

        print(f"📊 Processing {len(paths)} path(s)")

        # Process each path
        for path_index, path in enumerate(paths):
            d = path.get("d")
            if not d:
                print(f"⚠️ Warning: Path {path_index} has no 'd' attribute.")
                continue
                
            try:
                path_obj = parse_path(d)
            except Exception as e:
                print(f"❌ Error parsing path {path_index} data: {str(e)}")
                continue

            # Get continuous subpaths
            subpaths = [Path(*subpath) for subpath in path_obj.continuous_subpaths()]
            if not subpaths:
                print(f"⚠️ No subpaths found in path {path_index}.")
                continue

            print(f"📍 Path {path_index}: {len(subpaths)} subpath(s)")

            # Sample points from all subpaths
            all_subpath_points = []
            for subpath_index, subpath in enumerate(subpaths):
                points = self.path_processor.sample_bezier_path(subpath, samples_per_segment=20)
                if len(points) >= 3:  # Need at least 3 points for a valid polygon
                    all_subpath_points.append(points)
                    print(f"  📌 Subpath {subpath_index}: {len(points)} points sampled")
                else:
                    print(f"  ⚠️ Subpath {subpath_index}: Too few points ({len(points)}), skipping")

            if not all_subpath_points:
                print(f"❌ No valid subpaths in path {path_index}")
                continue

            # ===============================================================================
            # 🔧 SIMPLIFIED OFFSET LOGIC - NO WINDING COMPLEXITY
            # ===============================================================================
            
            print(f"🎯 Applying {offset_mm}mm offset to all subpaths (no winding separation)")
            
            # Create single clipper offset object
            clipper_offset = pyclipper.PyclipperOffset()
            
            # Add ALL subpaths to the same offset operation
            valid_subpaths_added = 0
            for subpath_index, points in enumerate(all_subpath_points):
                try:
                    # Scale points for precision
                    scaled_points = [[int(p[0] * SCALE), int(p[1] * SCALE)] for p in points]
                    
                    # Add to clipper (all paths get same treatment)
                    clipper_offset.AddPath(scaled_points, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
                    valid_subpaths_added += 1
                    
                    print(f"  ✅ Added subpath {subpath_index} to offset operation")
                    
                except Exception as e:
                    print(f"  ❌ Failed to add subpath {subpath_index}: {str(e)}")
                    continue
            
            if valid_subpaths_added == 0:
                print(f"❌ No valid subpaths added for path {path_index}")
                continue
            
            # Execute offset - same direction for ALL subpaths
            try:
                offset_solution = clipper_offset.Execute(delta)
                print(f"🎯 Offset executed: {len(offset_solution)} result path(s)")
            except Exception as e:
                print(f"❌ Offset execution failed for path {path_index}: {str(e)}")
                continue
            
            # Check if offset produced results
            if not offset_solution:
                print(f"⚠️ Warning: Offset produced no results for path {path_index}. Offset {offset_mm}mm may be too large.")
                continue
            
            # Convert offset results back to SVG path data
            offset_path_parts = []
            for result_index, result_path in enumerate(offset_solution):
                try:
                    # Unscale points
                    unscaled_points = [[p[0] / SCALE, p[1] / SCALE] for p in result_path]
                    
                    # Simplify path (remove redundant points)
                    simplified_points = self.path_processor.simplify_path(unscaled_points)
                    
                    if len(simplified_points) >= 3:
                        # Convert to SVG path data
                        path_d = self.path_processor.points_to_path_d(simplified_points)
                        offset_path_parts.append(path_d)
                        print(f"  ✅ Result {result_index}: {len(simplified_points)} points → path data")
                    else:
                        print(f"  ⚠️ Result {result_index}: Too few points after simplification")
                        
                except Exception as e:
                    print(f"  ❌ Failed to process result {result_index}: {str(e)}")
                    continue
            
            # Update path with offset results
            if offset_path_parts:
                # Combine all offset path parts
                combined_path_d = " ".join(offset_path_parts)
                path.set("d", combined_path_d)
                path.set("fill", "#ffa500")  # Orange fill for visibility
                path.set("fill-rule", "evenodd")
                print(f"✅ Path {path_index} updated with {len(offset_path_parts)} offset part(s)")
            else:
                print(f"❌ No valid offset results for path {path_index}")
                # Keep original path as fallback
                continue

        print(f"🎯 Offset processing complete")

        # ===============================================================================
        # 💾 SAVE OFFSET SVG TO TEMPORARY FILE
        # ===============================================================================
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as temp_file:
                temp_file_path = temp_file.name
                
            # Write the SVG file
            with open(temp_file_path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write(f'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="{viewBox}">\n')
                
                # Write all paths
                for path in svg_root.findall(".//{http://www.w3.org/2000/svg}path"):
                    d = path.get("d", "")
                    fill = path.get("fill", "#ffa500")
                    fill_rule = path.get("fill-rule", "evenodd")
                    
                    if d:  # Only write paths with valid data
                        f.write(f'  <path d="{d}" fill="{fill}" fill-rule="{fill_rule}"/>\n')
                
                f.write('</svg>')
                
            print(f"💾 Temporary offset SVG created: {temp_file_path}")
            print(f"📏 Offset applied: {offset_mm}mm")
            
            return temp_file_path
            
        except Exception as e:
            print(f"❌ Error creating temporary SVG file: {str(e)}")
            return None