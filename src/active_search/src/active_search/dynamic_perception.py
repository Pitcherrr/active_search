import numpy as np
import open3d as o3d

from vgn.utils import map_cloud_to_grid
from robot_helpers import perception


class SceneTSDFVolume:
    def __init__(self, length, resolution):
        self.length = length
        self.resolution = resolution
        self.voxel_size = self.length / self.resolution
        self.sdf_trunc = 4 * self.voxel_size
        # self.sdf_trunc = self.voxel_size
        self.o3dvol = o3d.pipelines.integration.UniformTSDFVolume(
            length=self.length,
            resolution=self.resolution,
            sdf_trunc=self.sdf_trunc,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
        )
        # self.o3dvol = o3d.pipelines.integration.ScalableTSDFVolume(
        #     voxel_length=self.length / self.resolution,
        #     sdf_trunc=self.sdf_trunc,
        #     color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
        # )

    def integrate(self, depth_img, intrinsic, extrinsic):

        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.empty_like(depth_img)),#you can add the actual image from the camera here, maybe is was too slow?
            o3d.geometry.Image(depth_img),
            depth_scale=1.0,
            #depth_truc = 3,
            convert_rgb_to_intensity=False,
        )
        intrinsic_o3d = intrinsic.to_o3d()
        self.o3dvol.integrate(rgbd, intrinsic_o3d, extrinsic)



    def get_scene_cloud(self):
        return self.o3dvol.extract_point_cloud()

    def get_map_cloud(self):
        return self.o3dvol.extract_voxel_point_cloud()

    def get_grid(self):
        map_cloud = self.get_map_cloud()
        points = np.asarray(map_cloud.points)
        distances = np.asarray(map_cloud.colors)[:, [0]]
        return map_cloud_to_grid(self.voxel_size, points, distances)


def create_tsdf(size, resolution, imgs, intrinsic, views):
    tsdf = DyUniTSDFVolume(size, resolution)
    for img, view in zip(imgs, views):
        tsdf.integrate(img, intrinsic, view.inv())
    return tsdf