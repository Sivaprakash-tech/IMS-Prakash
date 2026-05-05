---

#  Incident Management System (IMS)

A scalable **Incident Management System** built using microservices architecture, supporting real-time signal ingestion, incident tracking, RCA management, and high-load processing.

---

#  System Architecture

The system follows a distributed architecture:

* **Backend (FastAPI)** → Handles signal ingestion & processing
* **Redis** → Acts as a queue (buffer + backpressure)
* **MongoDB** → Stores raw signals
* **PostgreSQL (TimescaleDB)** → Stores incidents
* **Streamlit Dashboard** → Visualizes system metrics
* **Locust** → Load testing

### Data Flow

```
Locust → Backend → Redis Queue → Workers → MongoDB + PostgreSQL → Dashboard(frontend)
```
---

# Tech Stack

| Component        | Technology               |
| ---------------- | ------------------------ |
| Backend          | FastAPI                  |
| Queue            | Redis                    |
| Signals Storage  | MongoDB                  |
| Incidents DB     | PostgreSQL (TimescaleDB) |
| Dashboard        | Streamlit                |
| Load Testing     | Locust                   |
| Containerization | Docker                   |
| Orchestration    | Kubernetes (KIND)        |

---

#  Tech Stack Decisions

## FastAPI → High-performance async framework that efficiently handles multiple concurrent requests. Ideal for real-time signal ingestion with low latency.
## Redis → Used as an in-memory queue to buffer incoming signals and implement backpressure. Ensures smooth handling of high traffic without overloading the system.
## MongoDB → Stores raw signals with a flexible schema, allowing easy handling of varying data formats. Optimized for high write throughput.
## PostgreSQL → Used for incident management with strong ACID consistency. Ensures reliable tracking of incident states and RCA data.
## Streamlit → Enables quick development of an interactive dashboard with minimal frontend effort. Provides real-time visualization of system metrics.
## Kubernetes (KIND) → Manages container orchestration, scaling, and self-healing of services. Ensures the system is resilient and production-ready.
## Docker → Containerizes all services for consistent and portable deployments. Simplifies integration with Kubernetes.

---

#  Docker Setup & Execution

### 1️) Clone Repository

```bash
git clone https://github.com/Sivaprakash-tech/IMS-Prakash.git
cd IMS-Prakash
```

### 2️) Run Application

```bash
docker compose up --build
```

### 3️) Verify Containers

```bash
docker ps
```



```markdown
![Docker Containers](images/01-docker-containers.png)
```

---

### 4️) Backend Health Check

```markdown
![Health](images/02-health-check.png)
```


---

### 5️) Load Testing (Docker)

```markdown
![Locust Stats](images/03-locust-stats.png)
![Locust Charts](images/04-locust-charts.png)
```

---

#  Kubernetes Deployment (KIND)

### 1️) Create Cluster

```bash
kind create cluster --config k8s/kind-cluster.yaml
```

### 2️) Build Images

```bash
docker build -t ims-backend:local backend/
docker build -t ims-dashboard:local dashboard/
```

### 3️) Load Images

```bash
kind load docker-image ims-backend:local --name ims
kind load docker-image ims-dashboard:local --name ims
```

### 4️) Deploy

```bash
kubectl apply -f k8s/
```

### 5️) Verify

```bash
kubectl get pods -n ims
```


```markdown
![K8s Pods](images/05-k8s-pods.png)
```

✔ All pods in **Running (1/1)** state

---

### 6️) Dashboard(Front-end)

```markdown
![Dashboard](images/06-dashboard.png)
```


---

### 7️) Incident Details

```markdown
![Incident Detail](images/07-incident-detail.png)
```

# Tracks:

* Severity
* State
* Time

---

### 8️) RCA Form

```markdown
![RCA](images/08-rca.png)
```

 # RCA Form allows to Submits The Following

* Root cause
* Fix
* Prevention

---

### 9️) Load Testing (Kubernetes)

```bash
kubectl apply -f k8s/08-locust.yaml
```

```markdown
![Locust K8s](images/09-locust-k8s.png)
```

---

#  Access URLs

##  Docker

| Service   | URL                                                      |
| --------- | -------------------------------------------------------- |
| Backend   | [http://localhost:9000/docs](http://localhost:9000/docs) |
| Dashboard | [http://localhost:8600](http://localhost:8600)           |
| Locust    | [http://localhost:8090](http://localhost:8090)           |

---

##  Kubernetes (KIND)

| Service   | URL                                                      |
| --------- | -------------------------------------------------------- |
| Backend   | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Dashboard | [http://localhost:8501](http://localhost:8501)           |
| Locust    | [http://localhost:8089](http://localhost:8089)           |

---
##  Concurrency & Scaling

- The system is designed to handle **high-volume incoming signals concurrently** using an asynchronous backend (FastAPI).  
- A **Redis-based queue** buffers incoming requests, decoupling ingestion from processing and ensuring smooth flow under heavy load.  
- Multiple background **worker processes consume signals asynchronously**, enabling parallel processing and improving throughput.  
- A **queue threshold (backpressure mechanism)** prevents system overload by controlling incoming traffic when capacity limits are reached.  
- This architecture minimizes contention and ensures **safe updates without race conditions** during incident processing.  

---

##  Resilience & Testing

- The system was tested using **Locust** to simulate real-world load scenarios with **200+ requests per second**.  
- Redis-based buffering ensures that sudden traffic spikes do not crash the system, providing **fault tolerance under load**.  
- The backend includes mechanisms to **gracefully handle failures**, ensuring continuity even if individual components are temporarily unavailable.  
- Basic retry handling ensures that **critical database operations are not lost**, improving reliability.  
- Overall, the system demonstrates **stable performance, controlled failure handling, and recovery capability**.  

---

##  Low-Level Design (LLD)

- The system follows a **modular architecture**, separating responsibilities into:  
  - **API Layer** → Handles request ingestion  
  - **Worker Layer** → Processes signals and updates incidents  
- This clear separation ensures better **maintainability, scalability, and debugging**.  
- Configuration is managed using **Kubernetes ConfigMaps and Secrets**, making the system environment-independent and secure.  
- The backend is designed to be **stateless**, allowing easy horizontal scaling across multiple instances.  
- The design promotes **separation of concerns, loose coupling, and high cohesion**, which are key principles of robust system design.  
---
#  Challenges & Fixes From the Assignment:

* Fixed **ImagePullBackOff** → Loaded images into KIND
* Fixed **Mongo CrashLoopBackOff** → Adjusted probes
* Fixed **Backend readiness** → Updated health checks
* Fixed **Locust errors** → ConfigMap mounting

---
