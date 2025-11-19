import numpy as np
from svgpathtools import parse_path, CubicBezier, Line, Path

class PathProcessor:
    @staticmethod
    def sample_bezier_path(path, samples_per_segment=50):  # CHANGED: Default from 100 to 50
        segments = list(path)
        points = []
        for segment in segments:
            if isinstance(segment, CubicBezier):
                for t in np.linspace(0, 1, samples_per_segment):
                    point = segment.point(t)
                    points.append([point.real, point.imag])
            elif isinstance(segment, Line):
                points.append([segment.start.real, segment.start.imag])
                points.append([segment.end.real, segment.end.imag])
            else:
                print(f"Warning: Unsupported segment type in path: {type(segment)}")
                continue

        unique_points = []
        for point in points:
            if not unique_points or not np.allclose(unique_points[-1], point, atol=1e-4):
                unique_points.append(point)

        if unique_points and not np.allclose(unique_points[0], unique_points[-1], atol=1e-4):
            unique_points.append(unique_points[0])

        return unique_points

    @staticmethod
    def simplify_path(points, tolerance=0.5):
        if len(points) < 3:
            return points
        simplified = [points[0]]
        for i in range(1, len(points)):
            if not np.allclose(points[i], simplified[-1], atol=tolerance):
                simplified.append(points[i])
        if not np.allclose(simplified[0], simplified[-1], atol=tolerance):
            simplified.append(simplified[0])
        return simplified

    @staticmethod
    def is_counterclockwise(points):
        area = 0
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        return area > 0

    @staticmethod
    def points_to_path_d(points):
        def format_coord(x):
            s = f"{x:.3f}".rstrip("0").rstrip(".")
            if s.startswith("0."):
                s = s[1:]
            elif s.startswith("-0."):
                s = "-" + s[2:]
            return s
        d = f"M {format_coord(points[0][0])},{format_coord(points[0][1])} "
        for p in points[1:]:
            d += f"L {format_coord(p[0])},{format_coord(p[1])} "
        d += "Z"
        return d

    @staticmethod
    def polygon_to_path_d(points_str):
        points = [float(coord) for coord in points_str.strip().split()]
        if len(points) % 2 != 0:
            print("Warning: Invalid number of coordinates in polygon points.")
            return None

        coords = [(points[i], points[i+1]) for i in range(0, len(points), 2)]
        if not coords:
            return None

        d = f"M {coords[0][0]},{coords[0][1]} "
        for x, y in coords[1:]:
            d += f"L {x},{y} "
        d += "Z"
        return d

    @staticmethod
    def get_path_bounds(points):
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        return min(x_coords), max(x_coords), min(y_coords), max(y_coords)

    @staticmethod
    def center_points(points, ref_min_x, ref_max_x, ref_min_y, ref_max_y):
        if not points:
            return points

        min_x, max_x, min_y, max_y = PathProcessor.get_path_bounds(points)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        ref_center_x = (ref_min_x + ref_max_x) / 2
        ref_center_y = (ref_min_y + ref_max_y) / 2

        dx = ref_center_x - center_x
        dy = ref_center_y - center_y

        centered_points = [[p[0] + dx, p[1] + dy] for p in points]
        return centered_points