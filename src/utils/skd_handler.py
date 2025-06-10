
import os
import digitalhub as dh

def list_artifact(path:str):
    return os.listdir(path)

def download_artifact(artifact_name = "",
                    src_path = "",
                    project_name = ""):    
    print(f"downloading artifact: {artifact_name}, {artifact_name}")    
    # Crea progetto, togliere local quando useremo backend
    project = dh.get_or_create_project(project_name)
    artifact = project.get_artifact(artifact_name)
    return artifact.download(src_path)

def upload_artifact(artifact_name = "",
                    src_path = "",
                    project_name = ""):    
    print(f"Upload artifact: {artifact_name}, {artifact_name}")    
    # Crea progetto, togliere local quando useremo backend
    project = dh.get_or_create_project(project_name)
    project.log_artifact(name=artifact_name, kind="artifact", source=src_path)
    
