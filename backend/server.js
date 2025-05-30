
const express = require('express');
const cors = require('cors');
const { MongoClient } = require('mongodb');

const app = express();
app.use(cors());
app.use(express.json());

const uri = 'mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac';
const client = new MongoClient(uri);
const dbName = 'parksense';

let db;
client.connect().then(() => {
  db = client.db(dbName);
  console.log('Connected to MongoDB');
});

app.get('/api/current-logs', async (req, res) => {
  const carlogs = await db.collection('car_logs').find().toArray();
  res.json(carlogs);
});

app.get('/api/previous-logs', async (req, res) => {
  const visitors = await db.collection('visitors').find().toArray();
  res.json(visitors);
});

app.get('/api/slots', async (req, res) => {
  const slots = await db.collection('slots').find().toArray();
  res.json(slots);
});

const PORT = 5000;
app.listen(PORT, () => console.log(`Server running on http://localhost:${PORT}`));
