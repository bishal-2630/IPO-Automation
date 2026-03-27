import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../models/bank_account.dart';
import 'add_bank_screen.dart';

class BankListScreen extends StatefulWidget {
  @override
  _BankListScreenState createState() => _BankListScreenState();
}

class _BankListScreenState extends State<BankListScreen> {
  final ApiService api = ApiService();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: FutureBuilder<List<BankAccount>>(
        future: api.getBankAccounts(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.error_outline, color: Colors.red, size: 60),
                    SizedBox(height: 16),
                    Text(
                      "Failed to load bank accounts",
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                    ),
                    SizedBox(height: 8),
                    Text(
                      "This might be due to a connection issue or the server being updated. You can still add new credentials below.",
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey),
                    ),
                    SizedBox(height: 24),
                    ElevatedButton.icon(
                      onPressed: () => setState(() {}),
                      icon: Icon(Icons.refresh),
                      label: Text("Retry Connection"),
                    ),
                  ],
                ),
              ),
            );
          }

          final banks = snapshot.data ?? [];

          if (banks.isEmpty) {
            return RefreshIndicator(
              onRefresh: () async => setState(() {}),
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: MediaQuery.of(context).size.height * 0.7,
                    child: Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.account_balance, size: 80, color: Colors.grey[800]),
                          SizedBox(height: 16),
                          Text("No bank credentials added.", style: TextStyle(color: Colors.grey)),
                          Text("Add them to enable balance checks.", style: TextStyle(color: Colors.grey[600], fontSize: 12)),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () async => setState(() {}),
            child: ListView.builder(
              padding: EdgeInsets.all(12),
              itemCount: banks.length,
              itemBuilder: (context, index) {
                final bank = banks[index];
                return Card(
                  elevation: 2,
                  margin: EdgeInsets.symmetric(vertical: 8),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: Colors.deepPurple.withOpacity(0.1),
                      child: Icon(Icons.account_balance, color: Colors.deepPurple),
                    ),
                    title: Text(bank.bankDisplay, style: TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text("Phone: ${bank.phoneNumber}"),
                        if (bank.linkedAccountId != null)
                          Text("Linked to Account ID: ${bank.linkedAccountId}", style: TextStyle(color: Colors.blue, fontSize: 12)),
                      ],
                    ),
                    trailing: IconButton(
                      icon: Icon(Icons.delete_outline, color: Colors.redAccent),
                      onPressed: () => _confirmDelete(bank.id),
                    ),
                  ),
                );
              },
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          final result = await Navigator.push(
            context, 
            MaterialPageRoute(builder: (context) => AddBankScreen())
          );
          if (result == true) setState(() {});
        },
        child: Icon(Icons.add),
        backgroundColor: Colors.deepPurple,
      ),
    );
  }

  void _confirmDelete(int id) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text("Delete Credentials?"),
        content: Text("This will stop automated balance checks for this bank."),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text("Cancel")),
          TextButton(
            onPressed: () async {
              Navigator.pop(context);
              try {
                await api.deleteBankAccount(id);
                setState(() {});
              } catch (e) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Delete failed: $e")));
              }
            }, 
            child: Text("Delete", style: TextStyle(color: Colors.red))
          ),
        ],
      ),
    );
  }
}
