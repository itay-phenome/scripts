# docker/

  This folder contains **Dockerfiles and Docker Compose configurations**.

  ## Structure suggestion
  ```
  docker/
    <project-name>/
      Dockerfile
      docker-compose.yml
      .env.example
  ```

  ## Naming convention
  Group by project or service name inside subfolders.

  ## Examples of what goes here
  - Dockerfiles for custom images
  - docker-compose stacks (dev, staging, prod)
  - Multi-container application setups
  - Docker networking & volume configurations
