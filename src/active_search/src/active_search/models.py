import rospkg
from pathlib import Path
import torch
import torch.nn as nn
import torch.optim as optim
import os


class Autoencoder(nn.Module):
    def __init__(self):
        super(Autoencoder, self).__init__()

        self.get_path()

        # Encoder layers
        self.encoder = nn.Sequential(

            nn.Conv3d(2, 32, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=2, stride=2),

            nn.Conv3d(32, 64, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=2, stride=2),

            nn.Conv3d(64, 128, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),

            nn.Flatten(),  # Flatten the 3D tensor into a 1D vector
            nn.Linear(128 * 10 * 10 * 10, 512)
        )

        # Decoder layers
        self.decoder = nn.Sequential(

            nn.Linear(512, 128 * 10 * 10 * 10),  # Map from the latent space back to the decoder input shape
            nn.Unflatten(1, (128, 10, 10, 10)),  # Reshape the tensor back to 4D (batch_size, channels, height, width, depth)
            nn.ReLU(),

            nn.Conv3d(128, 64, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.Upsample(scale_factor=2),

            nn.Conv3d(64, 32, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.Upsample(scale_factor=2),

            nn.Conv3d(32, 2, kernel_size=3, stride=1, padding=1),
            nn.Sigmoid()
        )

    def forward(self, x):
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded 
    
    def get_path(self):
        rospack = rospkg.RosPack()
        pkg_root = Path(rospack.get_path("active_search"))
        self.model_path =  str(pkg_root)+"/models/autoencoder_weights.pth"


class GraspEval(nn.Module):
    def __init__(self):
        super(GraspEval, self).__init__()
        self.fc1 = nn.Linear(526, 256) 
        self.fc2 = nn.Linear(256, 128)  
        self.fc3 = nn.Linear(128, 1)

        self.optimizer = optim.Adam(self.parameters(), lr=0.05)
        rospack = rospkg.RosPack()
        pkg_root = Path(rospack.get_path("active_search"))
        self.model_path =  str(pkg_root)+"/models/graspnn_weights_3.pth"  

    def forward(self, x):
        x = self.fc1(x)
        x = torch.relu(x)
        x = self.fc2(x) 
        x = torch.relu(x)    
        x = self.fc3(x)
        # output = torch.softmax(x)    
        return x
    
    def save_model(self):
        torch.save(self.state_dict(), self.model_path)
    
    def load_model(self):
        self.load_state_dict(torch.load(self.model_path))

class ViewEval(nn.Module):
    def __init__(self):
        super(ViewEval, self).__init__()
        self.fc1 = nn.Linear(526, 256) 
        self.fc2 = nn.Linear(256, 128)  
        self.fc3 = nn.Linear(128, 1)   

        self.optimizer = optim.Adam(self.parameters(), lr=0.05)

        rospack = rospkg.RosPack()
        pkg_root = Path(rospack.get_path("active_search"))
        self.model_path =  str(pkg_root)+"/models/viewnn_weights_3.pth"

    def forward(self, x):
        x = torch.relu(self.fc1(x))    
        x = torch.relu(self.fc2(x))    
        x = self.fc3(x)        
        return x
    
    def save_model(self):
        torch.save(self.state_dict(), self.model_path)

    def load_model(self):
        self.load_state_dict(torch.load(self.model_path))
    
