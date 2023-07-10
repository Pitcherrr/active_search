from controller_manager_msgs.srv import *
import copy
import cv_bridge
from geometry_msgs.msg import Twist
import numpy as np
import rospy
from sensor_msgs.msg import Image
from std_srvs.srv import Empty
import trimesh

from active_grasp.bbox import from_bbox_msg, AABBox
from active_grasp.timer import Timer
from active_grasp.srv import Reset, ResetRequest
from robot_helpers.ros import tf
from robot_helpers.ros.conversions import *
from robot_helpers.ros.panda import PandaArmClient, PandaGripperClient
from robot_helpers.ros.moveit import MoveItClient, create_collision_object_from_mesh
from robot_helpers.spatial import Rotation, Transform
from vgn.utils import look_at, cartesian_to_spherical, spherical_to_cartesian
from vgn.detection import select_local_maxima


class GraspController:
    def __init__(self, policy):
        self.policy = policy
        print(self.policy)
        self.load_parameters()
        self.init_service_proxies()
        self.init_robot_connection()
        self.init_moveit()
        self.init_camera_stream()

    def load_parameters(self):
        self.base_frame = rospy.get_param("~base_frame_id")
        self.T_grasp_ee = Transform.from_list(rospy.get_param("~ee_grasp_offset")).inv()
        self.T_grasp_drop = Transform.from_list(rospy.get_param("~grasp_drop_config"))
        self.cam_frame = rospy.get_param("~camera/frame_id")
        self.depth_topic = rospy.get_param("~camera/depth_topic")
        self.min_z_dist = rospy.get_param("~camera/min_z_dist")
        self.control_rate = rospy.get_param("~control_rate")
        self.linear_vel = rospy.get_param("~linear_vel")
        self.policy_rate = rospy.get_param("policy/rate")

    def init_service_proxies(self):
        self.reset_env = rospy.ServiceProxy("reset", Reset)
        self.switch_controller = rospy.ServiceProxy(
            "controller_manager/switch_controller", SwitchController
        )

    def init_robot_connection(self):
        self.arm = PandaArmClient()
        self.gripper = PandaGripperClient()
        topic = rospy.get_param("cartesian_velocity_controller/topic")
        self.cartesian_vel_pub = rospy.Publisher(topic, Twist, queue_size=10)

    def init_moveit(self):
        self.moveit = MoveItClient("panda_arm")
        rospy.sleep(1.0)  # Wait for connections to be established.
        self.moveit.move_group.set_planner_id("RRTstarkConfigDefault")
        self.moveit.move_group.set_planning_time(3.0)

    def switch_to_cartesian_velocity_control(self):
        req = SwitchControllerRequest()
        req.start_controllers = ["cartesian_velocity_controller"]
        req.stop_controllers = ["position_joint_trajectory_controller"]
        req.strictness = 1
        self.switch_controller(req)

    def switch_to_joint_trajectory_control(self):
        req = SwitchControllerRequest()
        req.start_controllers = ["position_joint_trajectory_controller"]
        req.stop_controllers = ["cartesian_velocity_controller"]
        req.strictness = 1
        self.switch_controller(req)

    def init_camera_stream(self):
        self.cv_bridge = cv_bridge.CvBridge()
        rospy.Subscriber(self.depth_topic, Image, self.sensor_cb, queue_size=1)

    def sensor_cb(self, msg):
        self.latest_depth_msg = msg

    def run(self):
        bbs = self.reset()
        # bbox = bbs.pop(-1)
        voxel_size = 0.0075
        x_off = 0.35
        y_off = -0.15
        z_off = 0.2

        bb_min = [x_off,y_off,z_off]
        bb_max = [40*voxel_size+x_off,40*voxel_size+y_off,40*voxel_size+z_off]
        self.bbox = AABBox(bb_min, bb_max)
        self.switch_to_cartesian_velocity_control()
        # grasps = []
        # for bb in bbs:
        #     # result = self.get_scene_grasps(bb)
        #     grasp = self.search_grasp(bb)
        #     # print(result)
        #     # result, grasp = result
        #     # if result is True:
        #     grasps.append(grasp)
        # print(grasps)

        while True:
            
            with Timer("search_time"):
                grasp = self.search_grasp(self.bbox)
            if grasp:
            # if grasp and self.grasp_ig(grasp) > 10:
                print("grasping")
                self.switch_to_joint_trajectory_control()
                with Timer("grasp_time"):
                    res = self.execute_grasp(grasp)
                    
                    if res == 'succeeded':
                        # remove_body = rospy.ServiceProxy('remove_body', Reset)
                        # response = from_bbox_msg(remove_body(ResetRequest()).bbox[0])

                        # self.policy.tsdf_cut(response)
                        self.switch_to_cartesian_velocity_control()
                        
                        # x = tf.lookup(self.base_frame, self.cam_frame)
                        # cmd = self.compute_velocity_cmd(self.policy.x_d, x)

                        # print(cmd)
                        # self.cartesian_vel_pub.publish(to_twist_msg(cmd))

                        # timer = rospy.Timer(rospy.Duration(1.0 / self.control_rate), self.send_vel_cmd)
                        # rospy.sleep(2)
                        # timer.shutdown()

                    elif res == "failed":
                        print("failed")
                        self.switch_to_cartesian_velocity_control()
                        # x = tf.lookup(self.base_frame, self.cam_frame)
                        # cmd = self.compute_velocity_cmd(self.policy.x_d, x)
                        # print(cmd)
                        # self.cartesian_vel_pub.publish(to_twist_msg(cmd))

                        # timer = rospy.Timer(rospy.Duration(1.0 / self.control_rate), self.send_vel_cmd)
                        # rospy.sleep(2)
                        # timer.shutdown()

                        # rospy.sleep(2)

 
                        # self.moveit.goto("ready", velocity_scaling=0.4)
                        # self.switch_to_joint_trajectory_control()

            else:
                res = "aborted"

        return self.collect_info(res)

    def reset(self):
        Timer.reset()
        self.moveit.scene.clear()
        res = self.reset_env(ResetRequest())
        rospy.sleep(1.0)  # Wait for the TF tree to be updated.
        bbs = res.bbox
        for i in range(len(bbs)):
            bbs[i] = from_bbox_msg(bbs[i])
        return bbs

    def search_grasp(self, bbox):
        self.view_sphere = ViewHalfSphere(bbox, self.min_z_dist)
        self.policy.activate(bbox, self.view_sphere)
        timer = rospy.Timer(rospy.Duration(1.0 / self.control_rate), self.send_vel_cmd)
        r = rospy.Rate(self.policy_rate)
        while not self.policy.done:
            img, pose, q = self.get_state()
            self.policy.update(img, pose, q)
            r.sleep()
        rospy.sleep(0.2)  # Wait for a zero command to be sent to the robot.
        self.policy.deactivate()
        timer.shutdown()
        return self.policy.best_grasp
    
    def get_scene_grasps(self, bbox):
        self.view_sphere = ViewHalfSphere(bbox, self.min_z_dist)
        self.policy.activate(bbox, self.view_sphere)
        origin = self.policy.T_base_task
        origin.translation[2] -= 0.05
        voxel_size, tsdf_grid = self.policy.tsdf.voxel_size, self.policy.tsdf.get_grid()
        # Then check whether VGN can find any grasps on the target
        out = self.policy.vgn.predict(tsdf_grid)
        grasps, qualities = select_local_maxima(voxel_size, out, threshold=0.8)

        for grasp in grasps:
            pose = origin * grasp.pose
            tip = pose.rotation.apply([0, 0, 0.05]) + pose.translation
            if bbox.is_inside(tip):
                return True, grasp
        return False, None
    
    def grasp_ig(self, grasp):
        #naive estimation of information gain from the grasping of an opject
        t = (self.policy.T_task_base * grasp.pose).translation
        i, j, k = (t / self.policy.tsdf.voxel_size).astype(int)
        bb_voxel = [5,5,5] #place holder for the actual target object size 
        # grasp_ig_mat = self.policy.occ_mat[i:i+2*bb_voxel[0],j-(bb_voxel[1]//2):j+(bb_voxel[1]//2),:] #most "correct approach" but gives some issues
        grasp_ig_mat = self.policy.occ_mat[i:,j-(bb_voxel[1]//2):j+(bb_voxel[1]//2),:] #most "correct approach" but gives some issues
        grasp_ig = grasp_ig_mat.sum()
        print("Grasp information gain:", grasp_ig)
        return grasp_ig




    def get_state(self):
        q, _ = self.arm.get_state()
        msg = copy.deepcopy(self.latest_depth_msg)
        img = self.cv_bridge.imgmsg_to_cv2(msg).astype(np.float32) * 0.001
        pose = tf.lookup(self.base_frame, self.cam_frame, msg.header.stamp)
        return img, pose, q

    def send_vel_cmd(self, event):
        if self.policy.x_d is None or self.policy.done:
            cmd = np.zeros(6)
        else:
            x = tf.lookup(self.base_frame, self.cam_frame)
            cmd = self.compute_velocity_cmd(self.policy.x_d, x)
        self.cartesian_vel_pub.publish(to_twist_msg(cmd))

    def compute_velocity_cmd(self, x_d, x):
        r, theta, phi = cartesian_to_spherical(x.translation - self.view_sphere.center)
        e_t = x_d.translation - x.translation
        e_n = (x.translation - self.view_sphere.center) * (self.view_sphere.r - r) / r
        linear = 1.0 * e_t + 6.0 * (r < self.view_sphere.r) * e_n
        scale = np.linalg.norm(linear) + 1e-6
        linear *= np.clip(scale, 0.0, self.linear_vel) / scale
        angular = self.view_sphere.get_view(theta, phi).rotation * x.rotation.inv()
        angular = 1.0 * angular.as_rotvec()
        return np.r_[linear, angular]

    def execute_grasp(self, grasp):
        self.create_collision_scene()
        T_base_grasp = self.postprocess(grasp.pose)
        self.gripper.move(0.08)
        T_base_approach = T_base_grasp * Transform.t_[0, 0, -0.06] * self.T_grasp_ee
        success, plan = self.moveit.plan(T_base_approach, 0.2, 0.2)
        if success:
            self.moveit.scene.clear()
            self.moveit.execute(plan)
            rospy.sleep(0.5)  # Wait for the planning scene to be updated
            self.moveit.gotoL(T_base_grasp * self.T_grasp_ee)
            rospy.sleep(0.5)
            self.gripper.grasp()
            #remove the body from the scene
            remove_body = rospy.ServiceProxy('remove_body', Reset)
            response = from_bbox_msg(remove_body(ResetRequest()).bbox[0])
            self.policy.tsdf_cut(response)
            #####################
            T_base_retreat = Transform.t_[0, 0, 0.05] * T_base_grasp * self.T_grasp_ee
            self.moveit.gotoL(T_base_retreat)
            rospy.sleep(1.0)  # Wait to see whether the object slides out of the hand
            success = self.gripper.read() > 0.002
            T_drop_location = T_base_retreat * self.T_grasp_drop
            # self.moveit.gotoL(T_drop_location)
            self.moveit.goto([0.79, -0.79, 0.0, -2.356, 0.0, 1.57, 0.79])
            return "succeeded" if success else "failed"
        else:
            return "no_motion_plan_found"

    def create_collision_scene(self):
        # Segment support surface
        cloud = self.policy.tsdf.get_scene_cloud()
        cloud = cloud.transform(self.policy.T_base_task.as_matrix())
        _, inliers = cloud.segment_plane(0.01, 3, 1000)
        support_cloud = cloud.select_by_index(inliers)
        cloud = cloud.select_by_index(inliers, invert=True)
        # o3d.io.write_point_cloud(f"{time.time():.0f}.pcd", cloud)

        # Add collision object for the support
        self.add_collision_mesh("support", compute_convex_hull(support_cloud))

        # Cluster cloud
        labels = np.array(cloud.cluster_dbscan(eps=0.01, min_points=8))

        # Generate convex collision objects for each segment
        self.hulls = []

        if len(labels) == 0: #with active seach sometimes this is empty
            self.search_grasp(self.bbox)

        if len(labels) > 0:
            for label in range(labels.max() + 1):
                segment = cloud.select_by_index(np.flatnonzero(labels == label))
                try:
                    hull = compute_convex_hull(segment)
                    name = f"object_{label}"
                    self.add_collision_mesh(name, hull)
                    self.hulls.append(hull)
                except:
                    # Qhull fails in some edge cases
                    pass
        else:
            self.search_grasp(self.bbox)

    def add_collision_mesh(self, name, mesh):
        frame, pose = self.base_frame, Transform.identity()
        co = create_collision_object_from_mesh(name, frame, pose, mesh)
        self.moveit.scene.add_object(co)

    def postprocess(self, T_base_grasp):
        rot = T_base_grasp.rotation
        if rot.as_matrix()[:, 0][0] < 0:  # Ensure that the camera is pointing forward
            T_base_grasp.rotation = rot * Rotation.from_euler("z", np.pi)
        T_base_grasp *= Transform.t_[0.0, 0.0, 0.01]
        return T_base_grasp

    def collect_info(self, result):
        points = [p.translation for p in self.policy.views]
        d = np.sum([np.linalg.norm(p2 - p1) for p1, p2 in zip(points, points[1:])])
        info = {
            "result": result,
            "view_count": len(points),
            "distance": d,
        }
        info.update(self.policy.info)
        info.update(Timer.timers)
        return info


def compute_convex_hull(cloud):
    hull, _ = cloud.compute_convex_hull()
    triangles, vertices = np.asarray(hull.triangles), np.asarray(hull.vertices)
    return trimesh.base.Trimesh(vertices, triangles)


class ViewHalfSphere:
    def __init__(self, bbox, min_z_dist):
        self.center = bbox.center
        self.r = 0.5 * bbox.size[2] + min_z_dist

    def get_view(self, theta, phi):
        eye = self.center + spherical_to_cartesian(self.r, theta, phi)
        up = np.r_[1.0, 0.0, 0.0]
        return look_at(eye, self.center, up)

    def sample_view(self):
        raise NotImplementedError
