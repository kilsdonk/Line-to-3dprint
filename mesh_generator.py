# modified_mesh_generator.py - Enhanced version with FORCE CLOCKWISE authority
import trimesh
import numpy as np
from scipy.spatial import Delaunay

class EnhancedMeshGenerator:
    """
    Enhanced version of MeshGenerator with FORCE CLOCKWISE authority for 3D printing
    """
    
    @staticmethod
    def force_clockwise_winding(points):
        """FORCE CLOCKWISE: Always make paths clockwise regardless of original direction"""
        if len(points) < 3:
            return points
        
        # Calculate signed area using shoelace formula
        area = 0
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        
        # If counterclockwise (positive area), reverse to make clockwise
        if area > 0:
            print("FORCE CLOCKWISE: Converting counterclockwise → clockwise for 3D printing")
            return points[::-1]
        else:
            print("FORCE CLOCKWISE: Already clockwise, keeping direction")
            return points
    
    @staticmethod
    def is_ear(points, prev_idx, curr_idx, next_idx, indices):
        """Check if a vertex forms a valid ear for clipping"""
        prev_point = points[prev_idx]
        curr_point = points[curr_idx]
        next_point = points[next_idx]
        
        # Check if the angle is convex (less than 180 degrees)
        v1 = [prev_point[0] - curr_point[0], prev_point[1] - curr_point[1]]
        v2 = [next_point[0] - curr_point[0], next_point[1] - curr_point[1]]
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        
        if cross <= 0:  # Concave angle
            return False
        
        # Check if any other vertex is inside this triangle
        for idx in indices:
            if idx in [prev_idx, curr_idx, next_idx]:
                continue
            if EnhancedMeshGenerator.point_in_triangle(points[idx], prev_point, curr_point, next_point):
                return False
        
        return True
    
    @staticmethod
    def point_in_triangle(point, a, b, c):
        """Check if a point is inside a triangle"""
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        
        d1 = sign(point, a, b)
        d2 = sign(point, b, c)
        d3 = sign(point, c, a)
        
        has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        
        return not (has_neg and has_pos)
    
    @staticmethod
    def triangulate_polygon_ear_clipping(points):
        """Triangulate polygon using ear clipping - fallback method"""
        if len(points) < 3:
            return []
        
        faces = []
        indices = list(range(len(points)))
        
        while len(indices) > 3:
            ear_found = False
            for i in range(len(indices)):
                prev_idx = indices[i-1]
                curr_idx = indices[i] 
                next_idx = indices[(i+1) % len(indices)]
                
                if EnhancedMeshGenerator.is_ear(points, prev_idx, curr_idx, next_idx, indices):
                    faces.append([prev_idx, curr_idx, next_idx])
                    indices.remove(curr_idx)
                    ear_found = True
                    break
            
            if not ear_found:
                # Fallback to fan triangulation if ear clipping fails
                print("Ear clipping failed, falling back to fan triangulation")
                return EnhancedMeshGenerator.fan_triangulate(points)
        
        if len(indices) == 3:
            faces.append(indices)
        
        return faces
    
    @staticmethod
    def fan_triangulate(points):
        """Simple fan triangulation from center point"""
        faces = []
        n = len(points)
        for i in range(1, n - 1):
            faces.append([0, i, i + 1])
        return faces
    
    @staticmethod
    def triangulate_polygon_delaunay(points):
        """Triangulate polygon using Delaunay triangulation with boundary constraint"""
        try:
            points_array = np.array(points)
            
            # Create Delaunay triangulation
            tri = Delaunay(points_array)
            
            # Filter triangles to keep only those inside the polygon
            valid_faces = []
            for simplex in tri.simplices:
                # Check if triangle centroid is inside the polygon
                centroid = np.mean(points_array[simplex], axis=0)
                if EnhancedMeshGenerator.point_in_polygon(centroid, points):
                    valid_faces.append(simplex.tolist())
            
            return valid_faces if valid_faces else EnhancedMeshGenerator.triangulate_polygon_ear_clipping(points)
            
        except Exception as e:
            print(f"Delaunay triangulation failed: {e}, falling back to ear clipping")
            return EnhancedMeshGenerator.triangulate_polygon_ear_clipping(points)
    
    @staticmethod
    def point_in_polygon(point, polygon):
        """Ray casting algorithm to determine if point is inside polygon"""
        x, y = point
        n = len(polygon)
        inside = False
        
        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    @staticmethod
    def triangulate_polygon(points):
        """Main triangulation method that tries multiple approaches"""
        if len(points) < 3:
            return []
        
        # Try Delaunay first for complex polygons with potential holes
        try:
            return EnhancedMeshGenerator.triangulate_polygon_delaunay(points)
        except:
            # Fall back to ear clipping
            try:
                return EnhancedMeshGenerator.triangulate_polygon_ear_clipping(points)
            except:
                # Final fallback to fan triangulation
                print("All advanced triangulation methods failed, using fan triangulation")
                return EnhancedMeshGenerator.fan_triangulate(points)
    
    @staticmethod
    def extrude_path(points, height, z_offset, name, filament_id, wall_loops=2):
        """
        Extrude a 2D path into a 3D mesh with FORCE CLOCKWISE authority for 3D printing
        
        Args:
            points: List of 2D points forming the path (already Y-flipped in SVG processing)
            height: Height of the extrusion
            z_offset: Z offset for the base of the extrusion
            name: Name of the mesh
            filament_id: ID of the filament to use (1-4)
            wall_loops: Number of wall loops to use (1-4)
            
        Returns:
            Trimesh mesh with metadata
        """
        points = np.array(points)
        if len(points) < 3:
            print(f"Error: Not enough points to extrude mesh ({name}): {len(points)} points")
            return None

        # Flip Y coordinates to match SVG coordinate system
        points = [[p[0], -p[1]] for p in points]
        print(f"Points for mesh ({name}) y-axis flipped to correct SVG orientation")

        # FORCE CLOCKWISE: Always ensure clockwise winding for consistent 3D printing
        points_corrected = EnhancedMeshGenerator.force_clockwise_winding(points)
        print(f"FINAL RESULT for {name}: CLOCKWISE (forced)")

        # Create vertices for top and bottom faces
        vertices = []
        faces = []

        # Add bottom vertices
        for x, y in points_corrected:
            vertices.append([x, y, z_offset])
        
        # Add top vertices
        for x, y in points_corrected:
            vertices.append([x, y, z_offset + height])

        n = len(points_corrected)
        
        # Create bottom face triangles using robust triangulation
        try:
            bottom_faces = EnhancedMeshGenerator.triangulate_polygon(points_corrected)
            faces.extend(bottom_faces)
            print(f"Bottom face triangulated with {len(bottom_faces)} triangles for {name}")
        except Exception as e:
            print(f"Bottom face triangulation failed for {name}: {e}")
            return None
        
        # Create top face triangles (reversed winding for upward normal)
        try:
            top_faces = EnhancedMeshGenerator.triangulate_polygon(points_corrected)
            # Offset indices for top face and reverse winding order for correct normal
            top_faces_offset = [[f[2] + n, f[1] + n, f[0] + n] for f in top_faces]
            faces.extend(top_faces_offset)
            print(f"Top face triangulated with {len(top_faces)} triangles for {name}")
        except Exception as e:
            print(f"Top face triangulation failed for {name}: {e}")
            return None

        # Create side faces (quads split into triangles) with correct winding
        side_faces = []
        for i in range(n - 1):
            # First triangle of the quad (ensure outward normal)
            side_faces.append([i, i + 1, i + n])
            # Second triangle of the quad (ensure outward normal)
            side_faces.append([i + 1, i + n + 1, i + n])
        
        # Connect last and first points with correct winding
        side_faces.append([n - 1, 0, 2 * n - 1])
        side_faces.append([0, n, 2 * n - 1])

        # Combine all faces
        all_faces = np.vstack([faces, side_faces]) if faces and side_faces else (faces if faces else side_faces)
        
        # Create the mesh
        try:
            mesh = trimesh.Trimesh(vertices=vertices, faces=all_faces)
            print(f"Created mesh for {name} with {len(vertices)} vertices and {len(all_faces)} faces")
        except Exception as e:
            print(f"Failed to create mesh for {name}: {e}")
            return None

        # Add metadata including name, filament_id, and wall_loops
        mesh.metadata = {
            "name": name,
            "filament_id": filament_id,
            "wall_loops": wall_loops
        }
        
        # Process and repair the mesh 
        try:
            mesh.process(validate=True)
            
            # Final repairs for 3D printing
            print(f"Applying final mesh repairs for 3D printing: {name}")
            trimesh.repair.fix_normals(mesh)
            trimesh.repair.fix_winding(mesh)
            mesh.fill_holes()

            # Additional repair for non-manifold meshes
            if not mesh.is_watertight:
                print(f"Attempting additional repairs for {name}")
                mesh.merge_vertices(digits_vertex=5)
                mesh.update_faces(mesh.nondegenerate_faces(height=1e-5))
                mesh.update_faces(mesh.unique_faces())
                trimesh.repair.fix_winding(mesh)
                trimesh.repair.fix_normals(mesh)
                mesh.fill_holes()
                mesh.remove_unreferenced_vertices()

            # Final status
            if not mesh.is_watertight:
                print(f"Warning: Mesh ({name}) still has non-manifold edges after repair. Is watertight: {mesh.is_watertight}")
            else:
                print(f"✓ Mesh ({name}) successfully repaired and ready for 3D printing. Is watertight: {mesh.is_watertight}")
                
        except Exception as e:
            print(f"Mesh repair failed for {name}: {e}")

        # Only return the mesh if it has faces
        return mesh if len(mesh.faces) > 0 else None

# Create a new MeshGenerator class that can be used as a drop-in replacement
class MeshGenerator:
    @staticmethod
    def extrude_path(points, height, z_offset, name, filament_id):
        """
        Enhanced version with FORCE CLOCKWISE authority for 3D printing
        
        Args:
            points: List of 2D points forming the path (already Y-flipped)
            height: Height of the extrusion
            z_offset: Z offset for the base of the extrusion
            name: Name of the mesh
            filament_id: ID of the filament to use (1-4)
            
        Returns:
            Trimesh mesh with metadata
        """
        # Default wall_loops based on name as requested by user
        wall_loops = 2
        if name == "Inside_white_1":
            wall_loops = 1  # Set to 1 as requested
        elif name == "Return_bottom":
            wall_loops = 3  # Set to 3 as requested
        elif name == "Return_top":
            wall_loops = 3  # Set to 3 as requested
        
        # Call the enhanced static method with FORCE CLOCKWISE authority
        return EnhancedMeshGenerator.extrude_path(
            points, height, z_offset, name, filament_id, wall_loops
        )