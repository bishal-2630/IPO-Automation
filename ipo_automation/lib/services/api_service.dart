import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/account.dart';
import '../models/bank_account.dart';

class ApiService {
  static const String baseUrl = 'https://bishal26-ipo-automation.hf.space/api';

  Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('token');
  }

  Future<void> saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('token', token);
  }

  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
  }

  Future<bool> register(String username, String password, String email, String firstName, String lastName) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/register/'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'username': username, 
        'password': password,
        'email': email,
        'first_name': firstName,
        'last_name': lastName,
      }),
    );
    if (response.statusCode == 201) {
      final data = json.decode(response.body);
      await saveToken(data['token']);
      return true;
    }
    return false;
  }

  Future<bool> login(String username, String password) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login/'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'username': username, 'password': password}),
    );
    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      await saveToken(data['token']);
      return true;
    }
    return false;
  }

  Future<List<Account>> getAccounts() async {
    final token = await getToken();
    print('DEBUG: Getting accounts from $baseUrl/accounts/');
    final response = await http.get(
      Uri.parse('$baseUrl/accounts/'),
      headers: {'Authorization': 'Token $token'},
    );
    print('DEBUG: Response Status: ${response.statusCode}');
    if (response.statusCode == 200) {
      List jsonResponse = json.decode(response.body);
      return jsonResponse.map((data) => Account.fromJson(data)).toList();
    } else {
      print('DEBUG: Error Body: ${response.body}');
      throw Exception('Failed to load accounts: status ${response.statusCode}');
    }
  }

  Future<List<dynamic>> getLogs() async {
    final token = await getToken();
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/logs/'),
        headers: {'Authorization': 'Token $token'},
      );
      print('DEBUG: Response Status: ${response.statusCode}');
      if (response.statusCode == 200) {
        return json.decode(response.body);
      } else {
        print('Failed to fetch logs: ${response.body}');
        throw Exception('Failed to fetch logs (${response.statusCode})');
      }
    } catch (e) {
      print('Failed to fetch logs: $e');
      rethrow;
    }
  }

  Future<void> addAccount(Map<String, dynamic> accountData) async {
    final token = await getToken();
    final response = await http.post(
      Uri.parse('$baseUrl/accounts/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode(accountData),
    );
    if (response.statusCode != 201) {
      throw Exception('Failed to add account: ${response.body}');
    }
  }
  
  Future<void> updateAccount(int id, Map<String, dynamic> data) async {
    final token = await getToken();
    final response = await http.patch(
      Uri.parse('$baseUrl/accounts/$id/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode(data),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update account: ${response.body}');
    }
  }

  Future<void> deleteAccount(int id) async {
    final token = await getToken();
    final response = await http.delete(
      Uri.parse('$baseUrl/accounts/$id/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode != 204) {
      throw Exception('Failed to delete account: ${response.body}');
    }
  }

  Future<void> saveFcmToken(String fcmToken, String deviceId) async {
    final token = await getToken();
    if (token == null) return;

    await http.post(
      Uri.parse('$baseUrl/fcm-tokens/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode({
        'token': fcmToken,
        'device_id': deviceId,
      }),
    );
  }

  // --- Bank Operations ---

  Future<List<BankAccount>> getBankAccounts() async {
    final token = await getToken();
    final response = await http.get(
      Uri.parse('$baseUrl/bank-accounts/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode == 200) {
      List jsonResponse = json.decode(response.body);
      return jsonResponse.map((data) => BankAccount.fromJson(data)).toList();
    } else {
      throw Exception('Failed to load bank accounts');
    }
  }

  Future<void> getHealthDiagnostics() async {
    try {
      final healthUrl = baseUrl.replaceAll('/api', '') + '/health/';
      print('DEBUG: Fetching Diagnostics from $healthUrl');
      final response = await http.get(Uri.parse(healthUrl));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        print('-----------------------------------------');
        print('🔧 BACKEND DIAGNOSTICS:');
        print('URL: $healthUrl');
        print('STATUS: ONLINE');
        print('VERSION: ${data['version']}');
        print('ENCRYPTION_KEY_LENGTH: ${data['encryption_key_length']}');
        print('ENCRYPTION_KEY_VALID: ${data['encryption_key_valid']}');
        if (data['encryption_error'] != null) {
          print('ENCRYPTION_ERROR: ${data['encryption_error']}');
        }
        print('BRANCH: ${data['branch']}');
        print('-----------------------------------------');
      } else {
        print('DEBUG: Diagnostics check failed with status ${response.statusCode} for $healthUrl');
        print('DEBUG: Error Body: ${response.body}');
      }
    } catch (e) {
      print('DEBUG: Error fetching diagnostics: $e');
    }
  }

  Future<void> addBankAccount(Map<String, dynamic> bankData) async {
    final token = await getToken();
    print('DEBUG: Adding bank account to $baseUrl/bank-accounts/');
    final response = await http.post(
      Uri.parse('$baseUrl/bank-accounts/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode(bankData),
    );
    print('DEBUG: Response Status: ${response.statusCode}');
    
    if (response.statusCode != 201) {
      print('DEBUG: Error detected. Fetching terminal diagnostics...');
      await getHealthDiagnostics();
      throw Exception('Failed to add bank account: ${response.body}');
    }
  }

  Future<void> deleteBankAccount(int id) async {
    final token = await getToken();
    final response = await http.delete(
      Uri.parse('$baseUrl/bank-accounts/$id/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode != 204) {
      throw Exception('Failed to delete bank account');
    }
  }

  Future<void> deleteLog(int id) async {
    final token = await getToken();
    final response = await http.delete(
      Uri.parse('$baseUrl/logs/$id/'),
      headers: {'Authorization': 'Token $token'},
    );
    if (response.statusCode != 204) {
      throw Exception('Failed to delete log');
    }
  }

  Future<void> markLogsAsRead() async {
    final token = await getToken();
    await http.post(
      Uri.parse('$baseUrl/logs/mark-as-read/'),
      headers: {'Authorization': 'Token $token'},
    );
  }

  Future<void> relayOtp(String? meroshareUser, String otpCode) async {
    final token = await getToken();
    final Map<String, dynamic> body = {'otp_code': otpCode};
    if (meroshareUser != null) {
      body['meroshare_user'] = meroshareUser;
    }
    
    print('DEBUG: Relaying OTP $otpCode to $baseUrl/bank-otps/');
    final response = await http.post(
      Uri.parse('$baseUrl/bank-otps/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token'
      },
      body: json.encode(body),
    );
    print('DEBUG: Relay Status: ${response.statusCode}');
    if (response.statusCode != 201) {
      print('DEBUG: Relay Error: ${response.body}');
      throw Exception('Failed to relay OTP: ${response.body}');
    }
  }
}
