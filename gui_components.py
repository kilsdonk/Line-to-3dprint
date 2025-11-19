from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt
from lxml import etree
import trimesh
import numpy as np
from svgpathtools import parse_path, Path
from pathlib import Path as FilePath
import os
import zipfile
import tempfile

from path_processor import PathProcessor
from svg_processor import SvgProcessor
from mesh_generator import MeshGenerator

class SvgTo3mfApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.path_processor = PathProcessor()
        self.svg_processor = SvgProcessor()
        self.mesh_generator = MeshGenerator()
        
        self.setWindowTitle("SVG to 3MF Generator - Simplified")
        self.setGeometry(100, 100, 400, 350)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.label_debug = QLabel("Debug: Version 179 Simplified (Inside_white_2, Inside_white_3, click_top removed)", self)
        self.label_debug.setStyleSheet("color: red; font-style: italic; font-size: 12px;")
        self.layout.addWidget(self.label_debug)

        self.label_file_inside = QLabel("Select Inside SVG File (Red):", self)
        self.label_file_inside.setStyleSheet("font-size: 14px;")
        self.layout.addWidget(self.label_file_inside)

        self.path_entry_inside = QLineEdit(self)
        self.path_entry_inside.setStyleSheet("font-size: 12px; padding: 5px;")
        self.layout.addWidget(self.path_entry_inside)

        self.browse_button_inside = QPushButton("Browse Inside SVG", self)
        self.browse_button_inside.setStyleSheet("background-color: #F8E7A6; color: black; font-size: 12px; padding: 5px;")
        self.browse_button_inside.clicked.connect(self.browse_svg_inside)
        self.layout.addWidget(self.browse_button_inside)

        self.label_file_outside = QLabel("Outside SVG with +1mm offset", self)
        self.label_file_outside.setStyleSheet("font-size: 14px; color: gray;")
        self.layout.addWidget(self.label_file_outside)

        self.label_bottom_height = QLabel("Bottom Height (mm):", self)
        self.label_bottom_height.setStyleSheet("font-size: 14px;")
        self.layout.addWidget(self.label_bottom_height)

        self.bottom_height_entry = QLineEdit("20.0", self)
        self.bottom_height_entry.setStyleSheet("font-size: 12px; padding: 5px;")
        self.layout.addWidget(self.bottom_height_entry)

        self.label_top_height = QLabel("Top Height (mm):", self)
        self.label_top_height.setStyleSheet("font-size: 14px;")
        self.layout.addWidget(self.label_top_height)

        self.top_height_entry = QLineEdit("20.0", self)
        self.top_height_entry.setStyleSheet("font-size: 12px; padding: 5px;")
        self.layout.addWidget(self.top_height_entry)

        self.generate_button = QPushButton("Generate 3MF", self)
        self.generate_button.setStyleSheet("background-color: #C7E2F5; color: black; font-size: 14px; font-weight: bold; padding: 10px;")
        self.generate_button.clicked.connect(self.generate_3mf)
        self.layout.addWidget(self.generate_button)

    def browse_svg_inside(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Inside SVG File", "", "SVG Files (*.svg)")
        if file_path:
            self.path_entry_inside.setText(file_path)

    def generate_3mf(self):
        svg_file_inside = self.path_entry_inside.text()
        if not svg_file_inside:
            QMessageBox.critical(self, "Error", "Please select an inside SVG file!")
            return

        svg_file_outside = None
        try:
            bottom_height = float(self.bottom_height_entry.text())
            top_height = float(self.top_height_entry.text())

            if bottom_height <= 0 or top_height <= 0:
                QMessageBox.critical(self, "Error", "Invalid height values!")
                return

            svg_file_outside = self.svg_processor.generate_offset_svg(svg_file_inside, offset_mm=1.0)
            if not svg_file_outside:
                QMessageBox.critical(self, "Error", "Failed to generate outside SVG!")
                return

            parser = etree.XMLParser(remove_blank_text=True)

            tree_inside = etree.parse(svg_file_inside, parser)
            namespaces = {"svg": "http://www.w3.org/2000/svg"}
            svg_root_inside = tree_inside.getroot()
            viewBox_inside = svg_root_inside.get("viewBox")
            width_inside = svg_root_inside.get("width", "132.04")
            height_svg_inside = svg_root_inside.get("height", "200")

            if isinstance(width_inside, str):
                width_inside = float(width_inside.replace("mm", "").strip())
            else:
                width_inside = float(width_inside)

            if isinstance(height_svg_inside, str):
                height_svg_inside = float(height_svg_inside.replace("mm", "").strip())
            else:
                height_svg_inside = float(height_svg_inside)
            
            scale_factor_inside = 1.0
            vb_min_x, vb_max_x, vb_min_y, vb_max_y = 0, width_inside, 0, height_svg_inside
            if viewBox_inside:
                vb_vals = [float(v) for v in viewBox_inside.split()]
                if vb_vals[2] != 0 and vb_vals[3] != 0:
                    scale_factor_inside = min(width_inside / vb_vals[2], height_svg_inside / vb_vals[3])
                    vb_min_x, vb_max_x = vb_vals[0], vb_vals[0] + vb_vals[2]
                    vb_min_y, vb_max_y = vb_vals[1], vb_vals[1] + vb_vals[3]

            try:
                tree_outside = etree.parse(svg_file_outside, parser)
            except Exception as e:
                print(f"Error parsing generated outside SVG {svg_file_outside}: {str(e)}")
                os.remove(svg_file_outside)
                QMessageBox.critical(self, "Error", f"Failed to parse generated outside SVG: {str(e)}")
                return

            svg_root_outside = tree_outside.getroot()
            viewBox_outside = svg_root_outside.get("viewBox")
            width_outside = svg_root_outside.get("width", "132.04")
            height_svg_outside = svg_root_outside.get("height", "200")

            if isinstance(width_outside, str):
                width_outside = float(width_outside.replace("mm", "").strip())
            else:
                width_outside = float(width_outside)

            if isinstance(height_svg_outside, str):
                height_svg_outside = float(height_svg_outside.replace("mm", "").strip())
            else:
                height_svg_outside = float(height_svg_outside)
            
            scale_factor_outside = scale_factor_inside

            meshes = []
            inside_bounds = None

            paths_inside = tree_inside.xpath("//svg:path", namespaces=namespaces)
            paths_inside_polygons = tree_inside.xpath("//svg:polygon", namespaces=namespaces)

            for polygon in paths_inside_polygons:
                points = polygon.get("points")
                if not points:
                    print("Warning: Polygon element has no 'points' attribute in inside SVG.")
                    continue
                d = self.path_processor.polygon_to_path_d(points)
                if d:
                    path = etree.SubElement(tree_inside.getroot(), "{http://www.w3.org/2000/svg}path")
                    path.set("d", d)
                    path.set("fill", polygon.get("fill", "#ffa500"))
                    path.set("fill-rule", polygon.get("fill-rule", "evenodd"))
                    tree_inside.getroot().remove(polygon)

            paths_inside = tree_inside.xpath("//svg:path", namespaces=namespaces)
            if not paths_inside:
                print("No valid paths found in inside SVG.")
                os.remove(svg_file_outside)
                QMessageBox.critical(self, "Error", "No valid shapes to process!")
                return

            paths_outside = tree_outside.xpath("//svg:path", namespaces=namespaces)
            if not paths_outside:
                print("No valid paths found in outside SVG.")
                os.remove(svg_file_outside)
                QMessageBox.critical(self, "Error", "No valid shapes to process!")
                return

            inside_mesh_1 = None

            for path in paths_inside:
                d = path.get("d")
                if not d:
                    print("Warning: No path data found in inside SVG.")
                    continue
                path_obj = parse_path(d)
                points = self.path_processor.sample_bezier_path(path_obj, samples_per_segment=100)

                if len(points) < 3:
                    print("Warning: Too few points in inside path after sampling.")
                    continue

                scaled_points = [[point[0] * scale_factor_inside, point[1] * scale_factor_inside] for point in points]

                if inside_bounds is None:
                    inside_bounds = self.path_processor.get_path_bounds(scaled_points)

                x_coords = [p[0] for p in scaled_points]
                y_coords = [p[1] for p in scaled_points]
                width_model = max(x_coords) - min(x_coords)
                height_model = max(y_coords) - min(y_coords)
                print(f"Inside model dimensions: {width_model:.2f} x {height_model:.2f} mm")

                inside_mesh_1 = self.mesh_generator.extrude_path(scaled_points, bottom_height + top_height, z_offset=0.1, name="Inside_white", filament_id=4)

            top_mesh = None
            bottom_mesh = None

            for path in paths_outside:
                d = path.get("d")
                if not d:
                    print("Warning: No path data found in outside SVG.")
                    continue
                path_obj = parse_path(d)
                points = self.path_processor.sample_bezier_path(path_obj, samples_per_segment=100)

                if len(points) < 3:
                    print("Warning: Too few points in outside path after sampling.")
                    continue

                scaled_points = [[point[0] * scale_factor_outside, point[1] * scale_factor_outside] for point in points]

                if inside_bounds:
                    scaled_points = self.path_processor.center_points(scaled_points, inside_bounds[0], inside_bounds[1], inside_bounds[2], inside_bounds[3])

                x_coords = [p[0] for p in scaled_points]
                y_coords = [p[1] for p in scaled_points]
                width_model = max(x_coords) - min(x_coords)
                height_model = max(y_coords) - min(y_coords)
                print(f"Outside model dimensions: {width_model:.2f} x {height_model:.2f} mm")

                top_mesh = self.mesh_generator.extrude_path(scaled_points, top_height, z_offset=bottom_height, name="Return_top", filament_id=2)
                bottom_mesh = self.mesh_generator.extrude_path(scaled_points, bottom_height, z_offset=0.0, name="Return_bottom", filament_id=3)

            ordered_meshes = []
            if top_mesh:
                ordered_meshes.append(top_mesh)
            if bottom_mesh:
                ordered_meshes.append(bottom_mesh)
            if inside_mesh_1:
                ordered_meshes.append(inside_mesh_1)

            print("Layer order in ordered_meshes (first = bottom in Orcaslicer, last = top):")
            for i, mesh in enumerate(ordered_meshes):
                print(f"{i+1}. {mesh.metadata['name']} (z-offset: {mesh.bounds[0][2]})")

            if ordered_meshes:
                scene = trimesh.Scene()
                for mesh in ordered_meshes:
                    scene.add_geometry(mesh)
                
                output_file = str(FilePath(svg_file_inside).with_suffix(".3mf"))
                
                temp_file = "temp.3mf"
                scene.export(temp_file, file_type="3mf")

                with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                    with zipfile.ZipFile(temp_file, 'r') as temp_zf:
                        for item in temp_zf.infolist():
                            zf.writestr(item, temp_zf.read(item))

                os.remove(temp_file)
                os.remove(svg_file_outside)

                QMessageBox.information(self, "Success", f"3D model saved as: {output_file}")
            else:
                os.remove(svg_file_outside)
                QMessageBox.critical(self, "Error", "No valid shapes to export!")

        except Exception as e:
            if svg_file_outside and os.path.exists(svg_file_outside):
                os.remove(svg_file_outside)
            print(f"Exception occurred: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to generate 3MF: {str(e)}")