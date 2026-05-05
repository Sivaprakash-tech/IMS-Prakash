```markdown
# Incident Management System (IMS)

A scalable **Incident Management System** built with microservices and deployed using:

- Docker (local setup)
- Kubernetes (KIND cluster)
- Real-time dashboard (Streamlit)
- Load testing using Locust

---

#  System Architecture

- **Backend (FastAPI)** → Processes incoming signals
- **Redis** → Queue & buffering
- **MongoDB** → Stores raw signals
- **PostgreSQL (TimescaleDB)** → Stores incidents
- **Dashboard (Streamlit)** → Visualization
- **Locust** → Load testing

# Data flow:

Locust → Backend → Redis Queue → Workers → MongoDB + PostgreSQL → Dashboard

# ⚙️ Tech Stack

- FastAPI (Backend)
- Streamlit (Dashboard)
- PostgreSQL + TimescaleDB
- MongoDB
- Redis
- Locust (Load Testing)
- Docker & Kubernetes (KIND)

---

# Docker Implementation

<img width="1600" height="436" alt="image" src="https://github.com/user-attachments/assets/8a236eb4-1401-460e-9f3c-fb83c0acf401" />


 ✅ Containers Running



---

## ✅ Backend Health Check


::contentReference[oaicite:1]{index=1}


✔ All services connected:
- PostgreSQL ✅  
- MongoDB ✅  
- Redis ✅  

---

## ✅ Load Testing (Locust - Docker)


::contentReference[oaicite:2]{index=2}


✔ ~200+ RPS achieved  
✔ Real-time performance metrics  
✔ System handles load with controlled failures  

---

# ☸️ Kubernetes Implementation

## ✅ Pods Running (Main Proof)


::contentReference[oaicite:3]{index=3}


✔ All services deployed successfully  
✔ Pods in `Running` state  
✔ No critical failures  

---

## ✅ Dashboard (K8s)


::contentReference[oaicite:4]{index=4}


✔ Real-time metrics:
- Throughput (signals/sec)
- Queue usage
- Dropped signals

---

## ✅ Incident Details


::contentReference[oaicite:5]{index=5}


✔ Incident tracking:
- Component
- Severity
- State
- Timestamps

---

## ✅ RCA Form


::contentReference[oaicite:6]{index=6}


✔ Root Cause Analysis submission:
- Category
- Fix applied
- Prevention steps

---

## ✅ Locust (Kubernetes Load Test)


::contentReference[oaicite:7]{index=7}


✔ Load testing integrated inside Kubernetes  
✔ Generates real traffic to backend  

---

# 🚀 How to Run

## 1️⃣ Create Cluster
```bash
kind create cluster --config k8s/kind-cluster.yaml
````

## 2️⃣ Build Images

```bash
docker build -t ims-backend:local backend/
docker build -t ims-dashboard:local dashboard/
```

## 3️⃣ Load Images

```bash
kind load docker-image ims-backend:local --name ims
kind load docker-image ims-dashboard:local --name ims
```

## 4️⃣ Deploy

```bash
kubectl apply -f k8s/
```

## 5️⃣ Verify

```bash
kubectl get pods -n ims
kubectl get svc -n ims
```

---

# 🌐 Access

| Service   | URL                                                      |
| --------- | -------------------------------------------------------- |
| Backend   | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Dashboard | [http://localhost:8501](http://localhost:8501)           |
| Locust    | [http://localhost:8089](http://localhost:8089)           |

---

# 🛠️ Challenges & Fixes

### 🔴 ImagePullBackOff

✔ Fixed by loading images into KIND

### 🔴 Mongo CrashLoopBackOff

✔ Fixed readiness & liveness probes

### 🔴 Backend not ready

✔ Fixed health probe configuration

### 🔴 Locust failure

✔ Fixed ConfigMap mount for locustfile

---

# 📊 Key Results

* ✔ System handles **200+ requests/sec**
* ✔ Real-time monitoring dashboard
* ✔ Incident lifecycle tracking
* ✔ Fully containerized & orchestrated system

---

# 🧠 Learnings

* Kubernetes debugging (`logs`, `describe`)
* Stateful vs Stateless services
* ConfigMaps & Secrets usage
* Health probes tuning
* Load testing in distributed systems

---

# 👨‍💻 Author

**Prakash**

---

````

---

# 💬 Honest feedback

This README is now:
- ✔ **Visually attractive**
- ✔ **Well-structured**
- ✔ **Shows real work (Docker + K8s + Load)**
- ✔ **Interview-ready**

---

# 🔥 One small suggestion (optional but powerful)

If you want to make it even stronger:

👉 Add your **actual screenshots (uploaded images)** instead of generic queries

Example:

```markdown
![Docker Output](images/docker.png)
![K8s Pods](images/k8s-pods.png)
````

---

# 🚀 If you want next

I can help you:

* convert this into **PDF report**
* prepare **2-minute explanation script**
* or **GitHub repo polish (best formatting)**

Just tell me 👍
