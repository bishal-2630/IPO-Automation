import 'package:flutter/material.dart';
import '../services/api_service.dart';

class DashboardScreen extends StatefulWidget {
  @override
  _DashboardScreenState createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final ApiService api = ApiService();
  String _searchQuery = '';
  final TextEditingController _searchController = TextEditingController();
  late Future<List<dynamic>> _logsFuture;

  @override
  void initState() {
    super.initState();
    _logsFuture = api.getLogs();
  }

  Future<void> _refreshLogs() async {
    setState(() {
      _logsFuture = api.getLogs();
    });
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<dynamic>>(
      future: _logsFuture,
      builder: (context, snapshot) {
        // Only show centered loading on the very first load (when there's no data yet)
        if (snapshot.connectionState == ConnectionState.waiting && !snapshot.hasData) {
          return Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) return Center(child: Text("Error: ${snapshot.error}"));

        List<dynamic> allLogs = snapshot.data ?? [];

        // Filter out technical relay events/debug logs and block amount status noise
        final displayLogs = allLogs.where((l) {
          final String remark = (l['remark'] ?? '').toString().toLowerCase();
          final String status = (l['status'] ?? '').toString().toLowerCase();
          // Filter out relay/debug logs and block amount status updates
          return !remark.contains("relay") &&
                 !remark.contains("sms") &&
                 !remark.contains("otp") &&
                 !status.contains("relay") &&
                 !remark.contains("block amount status") &&
                 !status.contains("block amount status");
        }).toList();

        if (displayLogs.isEmpty) {
          return RefreshIndicator(
            onRefresh: _refreshLogs,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                SizedBox(
                  height: MediaQuery.of(context).size.height * 0.7,
                  child: Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.notifications_none, size: 60, color: Colors.grey),
                        SizedBox(height: 16),
                        Text("No notifications yet", style: TextStyle(color: Colors.grey)),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          );
        }

        final filteredLogs = _searchQuery.isEmpty
            ? displayLogs
            : displayLogs.where((l) {
                final String owner = (l['owner_name'] ?? '').toString().toLowerCase();
                final String user = (l['account_user'] ?? '').toString().toLowerCase();
                final String company = (l['company_name'] ?? '').toString().toLowerCase();
                return owner.contains(_searchQuery.toLowerCase()) || 
                       user.contains(_searchQuery.toLowerCase()) ||
                       company.contains(_searchQuery.toLowerCase());
              }).toList();

        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(12.0),
              child: TextField(
                controller: _searchController,
                onChanged: (value) {
                  setState(() {
                    _searchQuery = value;
                  });
                },
                decoration: InputDecoration(
                  hintText: "Filter notifications...",
                  prefixIcon: Icon(Icons.search, color: Colors.deepPurple),
                  suffixIcon: _searchQuery.isNotEmpty 
                    ? IconButton(
                        icon: Icon(Icons.clear, color: Colors.grey),
                        onPressed: () {
                          _searchController.clear();
                          setState(() {
                            _searchQuery = '';
                          });
                        },
                      )
                    : null,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(15),
                    borderSide: BorderSide.none,
                  ),
                  filled: true,
                  fillColor: Colors.deepPurple.withOpacity(0.05),
                  contentPadding: EdgeInsets.symmetric(vertical: 0, horizontal: 16),
                ),
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: _refreshLogs,
                child: ListView.builder(
                  padding: EdgeInsets.only(bottom: 80),
                  itemCount: filteredLogs.length,
                  itemBuilder: (context, index) {
                    final log = filteredLogs[index];
                    final status = log['status']?.toString() ?? '';
                    final isListed = status == 'Listed';
                    final isSuccess = status == 'Triggered' || status == 'Success' || isListed;
                    
                    return Dismissible(
                      key: Key(log['id'].toString()),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        alignment: Alignment.centerRight,
                        padding: EdgeInsets.symmetric(horizontal: 20),
                        color: Colors.redAccent,
                        child: Icon(Icons.delete, color: Colors.white),
                      ),
                      onDismissed: (direction) async {
                        try {
                          await api.deleteLog(log['id']);
                          setState(() {
                            allLogs.removeWhere((l) => l['id'] == log['id']);
                          });
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text("Notification deleted"), duration: Duration(seconds: 2)),
                          );
                        } catch (e) {
                          setState(() {}); // Refresh to restore item if delete failed
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text("Delete failed: $e"), backgroundColor: Colors.red),
                          );
                        }
                      },
                      child: Card(
                        margin: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        child: ListTile(
                          leading: CircleAvatar(
                            backgroundColor: isListed 
                                ? Colors.blue.withOpacity(0.1) 
                                : (isSuccess ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1)),
                            child: Icon(
                              isListed ? Icons.trending_up : (isSuccess ? Icons.check : Icons.error_outline),
                              color: isListed ? Colors.blue : (isSuccess ? Colors.green : Colors.red),
                            ),
                          ),
                          title: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  "${log['account_user']}",
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              if (log['owner_name'] != null && log['owner_name'].toString().isNotEmpty)
                                Container(
                                  padding: EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: Colors.deepPurple.withOpacity(0.1),
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  child: Text(
                                    log['owner_name'].toString(),
                                    style: TextStyle(
                                      fontSize: 10,
                                      color: Colors.deepPurple,
                                      fontWeight: FontWeight.bold,
                                    ),
                                  ),
                                ),
                            ],
                          ),
                          subtitle: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  if (log['is_read'] == false) ...[
                                    Container(
                                      width: 8,
                                      height: 8,
                                      decoration: BoxDecoration(color: Colors.blue, shape: BoxShape.circle),
                                    ),
                                    SizedBox(width: 6),
                                  ],
                                ],
                              ),
                              Text(
                                "${log['remark']}",
                                style: TextStyle(fontSize: 12, color: Colors.grey[400]),
                              ),
                            ],
                          ),
                          trailing: Text(
                            _formatTime(log['timestamp']),
                            style: TextStyle(fontSize: 11, color: Colors.grey),
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  String _formatTime(String? timestamp) {
    if (timestamp == null) return "";
    try {
      final dt = DateTime.parse(timestamp).toLocal();
      final monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      final month = monthNames[dt.month - 1];
      final day = dt.day;
      
      final hour = dt.hour > 12 ? dt.hour - 12 : (dt.hour == 0 ? 12 : dt.hour);
      final ampm = dt.hour >= 12 ? "PM" : "AM";
      final minute = dt.minute.toString().padLeft(2, '0');
      
      return "$month $day, $hour:$minute $ampm";
    } catch (e) {
      return "";
    }
  }
}
