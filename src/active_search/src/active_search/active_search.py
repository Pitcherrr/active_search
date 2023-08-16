import itertools
from numba import jit
import numpy as np
import torch
import torch.nn.functional as F
import open3d as o3d
import rospy
import time

from active_search.search_policy import MultiViewPolicy
from active_grasp.timer import Timer
from .models import Autoencoder, GraspEval, ViewEval


@jit(nopython=True)
def get_voxel_at(voxel_size, p):
    index = (p / voxel_size).astype(np.int64)
    return index if (index >= 0).all() and (index < 40).all() else None


# Note that the jit compilation takes some time the first time raycast is called
@jit(nopython=True)
def raycast(
    voxel_size,
    tsdf_grid,
    ori,
    pos,
    fx,
    fy,
    cx,
    cy,
    u_min,
    u_max,
    v_min,
    v_max,
    t_min,
    t_max,
    t_step,
):
    voxel_indices = []
    for u in range(u_min, u_max):
        for v in range(v_min, v_max):
            direction = np.asarray([(u - cx) / fx, (v - cy) / fy, 1.0])
            direction = ori @ (direction / np.linalg.norm(direction))
            t, tsdf_prev = t_min, -1.0
            while t < t_max:
                p = pos + t * direction
                t += t_step
                index = get_voxel_at(voxel_size, p)
                if index is not None:
                    i, j, k = index
                    tsdf = tsdf_grid[i, j, k]
                    if tsdf * tsdf_prev < 0 and tsdf_prev > -1:  # crossed a surface
                        break
                    voxel_indices.append(index)
                    tsdf_prev = tsdf
    return voxel_indices


class NextBestView(MultiViewPolicy):
    def __init__(self):
        super().__init__()
        self.min_z_dist = rospy.get_param("~camera/min_z_dist")
        self.max_views = rospy.get_param("nbv_grasp/max_views")
        self.min_gain = rospy.get_param("nbv_grasp/min_gain")
        self.downsample = rospy.get_param("nbv_grasp/downsample")
        self.load_models()
        self.compile()


    def load_models(self):
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.autoencoder = Autoencoder()
            self.autoencoder.load_state_dict(torch.load(self.autoencoder.model_path))
            self.autoencoder.to(self.device)

            self.grasp_nn = GraspEval()
            self.grasp_nn.to(self.device)
            
            self.view_nn = ViewEval()
            self.view_nn.to(self.device)

    def compile(self):
        # Trigger the JIT compilation
        raycast(
            1.0,
            np.zeros((40, 40, 40), dtype=np.float32),
            np.eye(3),
            np.zeros(3),
            1.0,
            1.0,
            1.0,
            1.0,
            0,
            1,
            0,
            1,
            0.0,
            1.0,
            0.1,
        )

    def activate(self, bbox, view_sphere):
        super().activate(bbox, view_sphere)

    def update(self, img, x, q):
        # First we integrate to gain data from the current scene
        # This includes the TSDF, occluded lovcations, and grasps  
 
        self.integrate(img, x, q)

        # Then generate the view candidates and their corresponding information gains
        views = self.generate_views(q)
        gains = [self.ig_fn(v, self.downsample) for v in views]

        # We now have 2 sets of actions that can be evaluated

        #Encode the scene using our trained autoencoder
        start = time.time()
        map_cloud = self.tsdf.get_map_cloud()
        occu_vec = o3d.utility.Vector3dVector(self.coordinate_mat)
        occu = o3d.geometry.PointCloud(points = occu_vec)
        cloud = self.join_clouds(map_cloud, occu)
        cloud_tensor = torch.tensor(np.asarray(cloud), dtype=torch.float32).to(self.device)
        encoded_voxel = self.autoencoder.encoder(cloud_tensor.view(1,2,40,40,40)) #need to view as a simgle sample
        print("Encode Time:", time.time()- start)
        print("Encode Tensor", encoded_voxel.shape)

        # We now have a vactor of length 512 that represents our scene and we can evaluate this scene along with our robots pose 
        # and each action from the 2 sets

        grasp_q = []
        grasp_t = []
        for grasp, quality in zip(self.grasps, self.qualities):
            grasp_nn_input = torch.cat((encoded_voxel, torch.tensor([np.concatenate((q, grasp.pose.to_list(), [quality]), dtype=np.float32)]).to(self.device)), 1)
            print(grasp_nn_input.shape)
            # print(grasp_nn_input)
            # From here evaluate the actions through the network
            grasp_val = self.grasp_nn(grasp_nn_input.squeeze())
            print("grasp val", grasp_val)
            grasp_q.append(grasp_val[0])
            grasp_t.append(grasp_val[1]) 

        view_q = []
        view_t = []
        for view, info_gain in zip(views, gains):
            view_nn_input = torch.cat((encoded_voxel, torch.tensor([np.concatenate((q, view.to_list(), [info_gain]), dtype=np.float32)]).to(self.device)), 1)
            print(view_nn_input.shape)
            # From here evaluate the actions through the network 
            view_val = self.view_nn(view_nn_input.squeeze())
            print("view val", view_val)
            view_q.append(view_val[0])
            view_t.append(view_val[1])

        # output is a set of actions with values and estimated completion time

        # Combine the grasp and view probabilities
        combined_probabilities = torch.cat((F.softmax(torch.stack(grasp_q), dim=0), F.softmax(torch.stack(view_q), dim=0)), dim=0)

        print(combined_probabilities)

        # Sample a single action index from the combined distribution
        selected_action_index = torch.multinomial(combined_probabilities, num_samples=1).item()

        grasp, view = False, False
        # Based on the selected index, determine whether it's a grasp or a view
        if selected_action_index < len(self.grasps):
            print("Grasp")
            grasp = True
            selected_action = self.grasps[selected_action_index]
            time_est = grasp_t[selected_action_index]
        else:
            print("View")
            view = True
            selected_action = views[selected_action_index - len(self.grasps)]
            time_est = view_t[selected_action_index]

        print(selected_action)

        return grasp, view, selected_action, time_est

        # if self.best_grasp_prediction_is_stable():
        # # if len(self.views) > self.max_views or self.best_grasp_prediction_is_stable():
        #     print("stable grasp")
        #     self.done = True
        #     print("Done")
        # else:
        #     print("not grasping")
        #     with Timer("state_update"):
        #         self.integrate(img, x, q)
        #     with Timer("view_generation"):
        #         views = self.generate_views(q)
        #     with Timer("ig_computation"):
        #         gains = [self.ig_fn(v, self.downsample) for v in views]
        #     with Timer("cost_computation"):
        #         costs = [self.cost_fn(v) for v in views]
        #     utilities = gains / np.sum(gains) - costs / np.sum(costs)
        #     self.vis.ig_views(self.base_frame, self.intrinsic, views, utilities)
        #     i = np.argmax(utilities)
        #     nbv, gain = views[i], gains[i]

        #     print(gain)

        #     if gain < self.min_gain and len(self.views) > self.T:
        #         print("done")
        #         self.done = True

        #     self.x_d = nbv

    def join_clouds(self, map_cloud, occu):
        grid_size = (40, 40, 40)
        grid1 = np.zeros(grid_size)
        points1 = np.asarray(map_cloud.points)
        distances = np.asarray(map_cloud.colors)[:, [0]]

        grid1 = np.zeros((40, 40, 40), dtype=np.float32)
        indices = (points1 // self.tsdf.voxel_size).astype(int)
        grid1[tuple(indices.T)] = distances.squeeze()
        # grid1[points1[:, 0], points1[:, 1], points1[:, 2]] = 1
        grid1 = grid1[np.newaxis, :, :, :]
        
        # Grid 2 is the occluded voxel locations
        grid2 = np.zeros(grid_size)
        points2 = np.asarray(occu.points).astype(int)
        grid2[points2[:, 0], points2[:, 1], points2[:, 2]] = 1
        grid2 = grid2[np.newaxis, :, :, :]

        # Concatenate the two voxel grids along the channel dimension (dim=0)
        combined_grid = np.concatenate((grid1, grid2), axis=0)

        return combined_grid

    def best_grasp_prediction_is_stable(self):
        if self.best_grasp:
            t = (self.T_task_base * self.best_grasp.pose).translation
            i, j, k = (t / self.tsdf.voxel_size).astype(int)
            qs = self.qual_hist[:, i, j, k]
            if np.count_nonzero(qs) == self.T and np.mean(qs) > 0.9:
                return True
        return False

    def generate_views(self, q):
        thetas = np.deg2rad([15, 30])
        phis = np.arange(8) * np.deg2rad(45)
        view_candidates = []
        for theta, phi in itertools.product(thetas, phis):
            view = self.view_sphere.get_view(theta, phi)
            if self.solve_cam_ik(q, view):
                view_candidates.append(view)
        print("generating",len(view_candidates),"views")
        return view_candidates

    def ig_fn(self, view, downsample):
        tsdf_grid, voxel_size = self.tsdf.get_grid(), self.tsdf.voxel_size
        tsdf_grid = -1.0 + 2.0 * tsdf_grid  # Open3D maps tsdf to [0,1]

        # Downsample the sensor resolution
        fx = self.intrinsic.fx / downsample
        fy = self.intrinsic.fy / downsample
        cx = self.intrinsic.cx / downsample
        cy = self.intrinsic.cy / downsample

        # Project bbox onto the image plane to get better bounds
        T_cam_base = view.inv()
        corners = np.array([T_cam_base.apply(p) for p in self.bbox.corners]).T
        u = (fx * corners[0] / corners[2] + cx).round().astype(int)
        v = (fy * corners[1] / corners[2] + cy).round().astype(int)
        u_min, u_max = u.min(), u.max()
        v_min, v_max = v.min(), v.max()

        t_min = 0.0  # self.min_z_dist
        t_max = corners[2].max()  # This bound might be a bit too short
        t_step = np.sqrt(3) * voxel_size  # Could be replaced with line rasterization

        # Cast rays from the camera view (we'll work in the task frame from now on)
        view = self.T_task_base * view
        ori, pos = view.rotation.as_matrix(), view.translation

        voxel_indices = raycast(
            voxel_size,
            tsdf_grid,
            ori,
            pos,
            fx,
            fy,
            cx,
            cy,
            u_min,
            u_max,
            v_min,
            v_max,
            t_min,
            t_max,
            t_step,
        )

        # Count rear side voxels within the bounding box
        # indices_list = np.unique(voxel_indices, axis=0)
        # print(indices_list)
        indices = set(map(tuple, voxel_indices)) 
        # print(indices)
        indices = indices.intersection(self.coord_set)
        indices_list = list(indices)
        
        bbox_min = self.T_task_base.apply(self.bbox.min) / voxel_size
        bbox_max = self.T_task_base.apply(self.bbox.max) / voxel_size
        mask = np.array([((i > bbox_min) & (i < bbox_max)).all() for i in indices_list], dtype = int)
        # i, j, k = indices_list[mask].T
        # i, j, k = zip(*indices_list[mask])
        if len(indices_list) == 0:
            return 0
        try:
            i, j, k = zip(*[tpl for i, tpl in enumerate(indices_list) if mask[i]])
        except:
            return 0


        tsdfs = tsdf_grid[i, j, k]
        ig = np.logical_and(tsdfs > -1.0, tsdfs < 0.0).sum()

        return ig

    def cost_fn(self, view):
        return 1.0
