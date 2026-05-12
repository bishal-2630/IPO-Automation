import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class ProfileScreen extends StatefulWidget {
  @override
  _ProfileScreenState createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final ApiService api = ApiService();
  Map<String, dynamic>? _userProfile;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _fetchProfile();
  }

  Future<void> _fetchProfile() async {
    try {
      final profile = await api.getUserProfile();
      setState(() {
        _userProfile = profile;
        _isLoading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load profile: $e')),
        );
      }
    }
  }

  Future<void> _logout() async {
    await api.logout();
    if (mounted) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (context) => LoginScreen()),
        (route) => false,
      );
    }
  }

  Future<void> _confirmDelete() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text('Delete Account?', style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold)),
        content: Text('This will permanently delete your account and all associated MeroShare data. This action cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text('Cancel', style: TextStyle(color: Colors.grey))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.redAccent,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text('Delete My Account'),
          ),
        ],
      ),
    );

    if (confirm == true) {
      try {
        await api.deleteUserAccount();
        await api.logout();
        if (mounted) {
          Navigator.of(context).pushAndRemoveUntil(
            MaterialPageRoute(builder: (context) => LoginScreen()),
            (route) => false,
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Failed to delete account: $e')),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final String firstName = _userProfile?['first_name'] ?? '';
    final String lastName = _userProfile?['last_name'] ?? '';
    final String fullName = (firstName.isEmpty && lastName.isEmpty)
        ? (_userProfile?['username'] ?? 'User')
        : '$firstName $lastName'.trim();
    
    final String? profileImageUrl = _userProfile?['profile_image_url'];

    return Scaffold(
      backgroundColor: Color(0xFF0F0F1E), // Dark premium background
      appBar: AppBar(
        title: Text('My Profile', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: true,
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: Colors.deepPurpleAccent))
          : SingleChildScrollView(
              padding: EdgeInsets.symmetric(horizontal: 24, vertical: 20),
              child: Column(
                children: [
                  // Profile Header Section
                  Center(
                    child: Stack(
                      children: [
                        Container(
                          padding: EdgeInsets.all(4),
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: LinearGradient(
                              colors: [Colors.deepPurpleAccent, Colors.blueAccent],
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                            ),
                          ),
                          child: CircleAvatar(
                            radius: 60,
                            backgroundColor: Color(0xFF1A1A2E),
                            backgroundImage: (profileImageUrl != null && profileImageUrl.isNotEmpty)
                                ? NetworkImage(profileImageUrl)
                                : null,
                            child: (profileImageUrl == null || profileImageUrl.isEmpty)
                                ? Icon(Icons.person, size: 70, color: Colors.grey[700])
                                : null,
                          ),
                        ),
                        Positioned(
                          bottom: 5,
                          right: 5,
                          child: Container(
                            padding: EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: Colors.deepPurpleAccent,
                              shape: BoxShape.circle,
                              border: Border.all(color: Color(0xFF0F0F1E), width: 2),
                            ),
                            child: Icon(Icons.camera_alt, size: 18, color: Colors.white),
                          ),
                        ),
                      ],
                    ),
                  ),
                  SizedBox(height: 24),
                  
                  // User Identity
                  Text(
                    fullName,
                    style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, letterSpacing: 0.5),
                    textAlign: TextAlign.center,
                  ),
                  SizedBox(height: 8),
                  Text(
                    '@${_userProfile?['username'] ?? 'username'}',
                    style: TextStyle(color: Colors.grey, fontSize: 16),
                  ),
                  SizedBox(height: 4),
                  Text(
                    _userProfile?['email'] ?? '',
                    style: TextStyle(color: Colors.grey.withOpacity(0.7), fontSize: 14),
                  ),
                  
                  SizedBox(height: 40),
                  
                  // Action Items
                  _buildSectionTitle('ACCOUNT SETTINGS'),
                  SizedBox(height: 12),
                  _buildProfileTile(
                    icon: Icons.person_outline,
                    title: 'Edit Profile',
                    onTap: () {}, // Future feature
                  ),
                  _buildProfileTile(
                    icon: Icons.security_outlined,
                    title: 'Security',
                    onTap: () {}, // Future feature
                  ),
                  _buildProfileTile(
                    icon: Icons.notifications_none_rounded,
                    title: 'Notification Settings',
                    onTap: () {}, // Future feature
                  ),
                  
                  SizedBox(height: 30),
                  _buildSectionTitle('DANGER ZONE'),
                  SizedBox(height: 12),
                  _buildProfileTile(
                    icon: Icons.logout_rounded,
                    title: 'Log Out',
                    onTap: _logout,
                    textColor: Colors.orangeAccent,
                  ),
                  _buildProfileTile(
                    icon: Icons.delete_forever_rounded,
                    title: 'Delete My Account',
                    onTap: _confirmDelete,
                    textColor: Colors.redAccent,
                    isLast: true,
                  ),
                  
                  SizedBox(height: 40),
                  Text(
                    'Version 3.18.0',
                    style: TextStyle(color: Colors.grey.withOpacity(0.4), fontSize: 12),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.only(left: 4.0),
        child: Text(
          title,
          style: TextStyle(
            color: Colors.grey,
            fontSize: 12,
            fontWeight: FontWeight.bold,
            letterSpacing: 1.2,
          ),
        ),
      ),
    );
  }

  Widget _buildProfileTile({
    required IconData icon,
    required String title,
    required VoidCallback onTap,
    Color? textColor,
    bool isLast = false,
  }) {
    return Column(
      children: [
        Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(12),
            child: Container(
              padding: EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              decoration: BoxDecoration(
                color: Color(0xFF1A1A2E),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white.withOpacity(0.05)),
              ),
              child: Row(
                children: [
                  Icon(icon, color: textColor ?? Colors.white.withOpacity(0.8), size: 22),
                  SizedBox(width: 16),
                  Text(
                    title,
                    style: TextStyle(
                      fontSize: 16,
                      color: textColor ?? Colors.white,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  Spacer(),
                  Icon(Icons.arrow_forward_ios_rounded, size: 14, color: Colors.grey),
                ],
              ),
            ),
          ),
        ),
        if (!isLast) SizedBox(height: 8),
      ],
    );
  }
}
